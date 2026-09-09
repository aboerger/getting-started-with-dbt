"""Shared machinery for publishing the dbt project bundles to OneLake.

A bundle is the zip a runner notebook installs from at session start
(``tools/fabric_bundle_bootstrap.py`` explains the notebook side). There are
two: ``NB_dbt_Runner_Spark`` (PySpark notebook, Spark Runtime 2.0) and
``NB_dbt_Runner`` (Python notebook, Python 3.11 kernel) run on different
images with different preinstalled packages, so each gets a bundle resolved
against its own runtime manifest. ``publish_dbt_bundle.py`` declares one
:class:`BundleSpec` per notebook and calls :func:`run`; everything else is
here, once. Ported from the AANA Hub repository's ``scripts/onelake_bundle.py``
(2026-09), minus the parts that only that monorepo needs (the
environment-runtime cross-check, the ``pyproject.toml`` pin lookup).

What ``run`` does:

1. **Resolve against the runtime.** ``pip install --dry-run --report`` of the
   spec's requirements plus the freshly built first-party wheels, targeted at
   the Fabric runtime's Python/platform (its CPython, manylinux2014 or
   manylinux_2_28, ``--only-binary=:all:``) and constrained by the vendored manifest of what
   that runtime already ships (``tools/runtime_constraints/``). A requirement
   that would force a runtime package to a different version is a *resolution
   failure* — loud, at publish time — unless the spec allow-lists it in
   ``overrides`` with a reason. Fabric's own environment publish (pip Full
   mode) silently shipped a protobuf upgrade that killed every Spark session at
   kernel start; this step is what catches that class of problem before it
   reaches a notebook.
2. **Prune what the runtime provides.** Anything resolved to the runtime's own
   version is not shipped; the bundle carries only what the runtime lacks plus
   the overrides. So no runtime package — compiled ones above all — is ever
   shadowed by the notebook's ``sys.path.insert(0)``, the zip stays small and
   the driver-side install takes seconds.
3. **Download exactly those wheels**, write ``wheels/requirements.txt`` (exact
   pins of every shipped wheel; the notebook installs it ``--no-deps``), copy
   ``fabric_bundle_bootstrap.py`` into the zip as ``bundle_bootstrap.py``, add
   ``deployment.json`` (build stamp + runtime + what was shipped/pruned/replaced)
   and upload the zip plus a sidecar ``deployment.json`` to the lakehouse.

Guards that fail the publish: a pyspark/py4j wheel in the bundle (it would
shadow the runtime's Spark) and a runtime package replaced without an override.

``--assemble-only`` runs steps 1–3 without authenticating or uploading (CI does
this on every pull request).

Azure imports are lazy so the resolve/assemble path needs only pip.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
CONSTRAINTS_DIR = TOOLS_DIR / "runtime_constraints"
BOOTSTRAP_SOURCE = TOOLS_DIR / "fabric_bundle_bootstrap.py"
BOOTSTRAP_ARCNAME = "bundle_bootstrap.py"

ONELAKE_URL = "https://onelake.dfs.fabric.microsoft.com"
STORAGE_SCOPE = "https://storage.azure.com/.default"
AUTH_RECORD_PATH = Path.home() / ".getting-started-with-dbt" / "onelake-publish-auth.json"
PERSISTENT_CACHE_NAME = "getting-started-with-dbt-onelake-publish"
GUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")

# Fabric kernels run on x86_64 Azure Linux 3.0 (glibc 2.38), every runtime so
# far. Accept both the classic manylinux2014 tag and manylinux_2_28: newer
# compiled wheels (mssql-python, dbt-fabric's driver) publish only the latter.
WHEEL_PLATFORMS = ("manylinux2014_x86_64", "manylinux_2_28_x86_64")
# Never ship Spark itself: the notebook's sys.path.insert(0) would make the
# bundle's copy shadow the runtime's, and the session dies or misbehaves.
RUNTIME_PROVIDED_PREFIXES = ("pyspark", "py4j")

_MANIFEST_BASE = (
    "https://raw.githubusercontent.com/microsoft/synapse-spark-runtime/main/Fabric/"
)


@dataclass(frozen=True)
class RuntimeProfile:
    """One Fabric notebook runtime: the Python its wheels must target and where
    Microsoft publishes the list of packages it preinstalls.

    ``manifest_format`` says how ``refresh_runtime_constraints.py`` reads that
    list: ``conda-yml`` for the Spark runtimes (one environment YML per
    runtime) or ``release-markdown`` for the Python-notebook image, whose
    release notes carry one package table per kernel (``manifest_section``
    names the table). ``manifest_url`` is either the file itself or, when
    ``manifest_is_index`` is set, a GitHub contents-API folder listing from
    which the newest ``.md`` release note is picked (the file name carries the
    release date, so a fixed URL would go stale).
    """

    version: str
    python_version: str
    constraints_file: str
    manifest_url: str
    description: str = ""
    manifest_format: str = "conda-yml"
    manifest_section: str = ""
    manifest_is_index: bool = False


_JUPYTER_INDEX = (
    "https://api.github.com/repos/microsoft/synapse-spark-runtime/contents/Fabric/Jupyter%201.0"
)

# One profile per runtime a notebook can run on. Adding one is one entry here
# plus `python tools/refresh_runtime_constraints.py --runtime <key>`.
RUNTIME_PROFILES: dict[str, RuntimeProfile] = {
    # Spark notebooks: the workspace's Spark settings select the runtime.
    "2.0": RuntimeProfile(
        "2.0", "3.13", "fabric-runtime-2.0-python313.txt",
        _MANIFEST_BASE + "Runtime%202.0%20(Spark%204.1)/Fabric-Python313-CPU.yml",
        description="Fabric Spark Runtime 2.0 (Spark 4.1), driver Python 3.13 - PySpark notebooks",
    ),
    # Python notebooks (no Spark): one image ("Jupyter 1.0") with three kernels; the
    # notebook's metadata picks the kernel, so the profile is per kernel.
    "python-3.11": RuntimeProfile(
        "python-3.11", "3.11", "fabric-python-notebook-python311.txt",
        _JUPYTER_INDEX,
        description="Fabric Python notebook (Jupyter 1.0 image), Python 3.11 kernel",
        manifest_format="release-markdown",
        manifest_section="Python3.11",
        manifest_is_index=True,
    ),
}


@dataclass(frozen=True)
class Override:
    """Permission to replace a runtime package, with the reason on record.

    ``specifier`` is appended to the package name as an extra requirement
    (``"==6.31.1"`` pins; ``""`` only lifts the runtime constraint and lets the
    resolver pick).
    """

    specifier: str
    reason: str


@dataclass(frozen=True)
class BundleSpec:
    name: str  # zip stem and deployment.json "project"
    default_runtime: str
    requirements: Sequence[str]
    first_party_dirs: Sequence[Path] = ()
    overrides: Mapping[str, Override] = field(default_factory=dict)
    default_destination: str = ""  # path under the lakehouse Files/ folder
    consumer: str = ""  # the notebook that installs this bundle (for messages and deployment.json)


@dataclass
class WheelReport:
    shipped: list[str] = field(default_factory=list)  # name==version
    pruned: list[str] = field(default_factory=list)  # name==version (runtime provides it)
    replaced: dict[str, dict] = field(default_factory=dict)  # name -> details
    first_party: list[str] = field(default_factory=list)


def use_os_trust_store() -> bool:
    """Make this process's TLS trust the operating system's certificate store.

    Behind a TLS-inspecting corporate proxy the proxy's root CA is in the
    Windows/macOS store but not in certifi's bundle, so ``requests`` (dbt's
    package hub client, the Azure SDK) and ``urllib`` fail with
    CERTIFICATE_VERIFY_FAILED. ``truststore`` fixes that in-process; pip does
    the same on its own (its default since 24.2), which is why the wheel
    downloads never needed it. Returns False when truststore is not installed
    (not in ``.venv-tools``) — the caller then falls back to whatever
    ``REQUESTS_CA_BUNDLE`` / ``SSL_CERT_FILE`` say.
    """
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True


# ---------------------------------------------------------------------------
# names, versions, constraints
# ---------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """PEP 503 project-name normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def versions_equal(a: str, b: str) -> bool:
    try:
        from packaging.version import Version

        return Version(a) == Version(b)
    except Exception:  # packaging missing or unparseable: literal comparison
        return a == b


def parse_wheel_filename(filename: str) -> tuple[str, str]:
    """Return (normalized name, version) from ``dist-ver(-build)-py-abi-plat.whl``."""
    parts = Path(filename).stem.split("-")
    if len(parts) < 5:
        raise ValueError(f"not a wheel filename: {filename}")
    return normalize_name(parts[0]), parts[1]


def load_constraints(profile: RuntimeProfile) -> tuple[dict[str, str], dict[str, str]]:
    """Vendored runtime pins as {name: version} plus the file's header facts."""
    path = CONSTRAINTS_DIR / profile.constraints_file
    if not path.is_file():
        raise SystemExit(
            f"Runtime constraints file missing: {path}. Generate it with "
            f"`python tools/refresh_runtime_constraints.py --runtime {profile.version}`."
        )
    pins: dict[str, str] = {}
    header: dict[str, str] = {"file": path.relative_to(REPO_ROOT).as_posix()}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = re.match(r"#\s*(source|manifest_sha256|manifest_section):\s*(\S+)", line)
            if match:
                header[match.group(1)] = match.group(2)
            continue
        name, _, version = line.partition("==")
        pins[normalize_name(name)] = version
    if not pins:
        raise SystemExit(f"Runtime constraints file is empty: {path}")
    return pins, header


def read_requirements_in(path: Path) -> list[str]:
    """The top-level requirements of a ``requirements/*.in`` file.

    Comments, blank lines and pip options (``-r``, ``-c``, ``--…``) are dropped;
    an inline ``# comment`` is stripped. The laptop venv, CI and the bundle
    all take their adapter pin from the same ``.in``, so there is one place to
    bump it.
    """
    requirements: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirements.append(line)
    if not requirements:
        raise SystemExit(f"No requirements found in {path}")
    return requirements


# ---------------------------------------------------------------------------
# resolve + download
# ---------------------------------------------------------------------------


def _pip(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", "pip", *args], capture_output=True, text=True
    )


def _fail(title: str, result: subprocess.CompletedProcess) -> None:
    raise SystemExit(f"{title}\n{result.stdout[-3000:]}\n{result.stderr[-6000:]}")


def build_first_party_wheels(dirs: Sequence[Path], dest: Path) -> list[Path]:
    """``pip wheel --no-deps`` each first-party package into ``dest``."""
    built: list[Path] = []
    for package_dir in dirs:
        if not (package_dir / "pyproject.toml").is_file():
            raise SystemExit(f"First-party package not found: {package_dir}")
        before = set(dest.glob("*.whl"))
        result = _pip(["wheel", "--no-deps", "--quiet", str(package_dir), "--wheel-dir", str(dest)])
        if result.returncode != 0:
            _fail(f"pip wheel of {package_dir.name} failed:", result)
        new = sorted(set(dest.glob("*.whl")) - before)
        if len(new) != 1:
            raise SystemExit(f"Expected one wheel from {package_dir}, got {[p.name for p in new]}")
        built.append(new[0])
    return built


def resolve_and_download(work: Path, spec: BundleSpec, profile: RuntimeProfile) -> tuple[Path, WheelReport, dict]:
    """Resolve the closure against the runtime, download what it lacks.

    Returns (wheels dir, report, constraints header facts).
    """
    wheels_dir = work / "wheels"
    wheels_dir.mkdir()
    runtime_pins, header = load_constraints(profile)

    first_party = build_first_party_wheels(list(spec.first_party_dirs), wheels_dir)
    first_party_names = {parse_wheel_filename(w.name)[0] for w in first_party}

    override_names = {normalize_name(n): o for n, o in spec.overrides.items()}
    constraints_path = work / f"constraints-runtime-{profile.version}.txt"
    constraints_path.write_text(
        "\n".join(f"{n}=={v}" for n, v in sorted(runtime_pins.items()) if n not in override_names)
        + "\n",
        encoding="utf-8",
    )
    requirements = [
        *spec.requirements,
        *(f"{name}{o.specifier}" for name, o in spec.overrides.items() if o.specifier),
        *(str(w) for w in first_party),
    ]
    target_args = [
        "--python-version", profile.python_version,
        *(arg for platform in WHEEL_PLATFORMS for arg in ("--platform", platform)),
        "--only-binary=:all:",
    ]

    report_path = work / "resolve-report.json"
    result = _pip([
        "install", "--dry-run", "--ignore-installed", "--quiet",
        "--report", str(report_path),
        "-c", str(constraints_path),
        *target_args, *requirements,
    ])
    if result.returncode != 0:
        _fail(
            f"Bundle '{spec.name}' cannot be resolved for Fabric runtime '{profile.version}' "
            f"({profile.description}; Python {profile.python_version}) against the runtime's pinned packages "
            f"({header['file']}). Either a requirement is incompatible with this runtime, "
            "or you intend to replace the runtime's copy of a package: add it to "
            "CONSTRAINT_OVERRIDES in the publish script with a reason (and a pin when only a "
            "specific version is known to work). pip said:",
            result,
        )
    resolved = json.loads(report_path.read_text(encoding="utf-8")).get("install", [])

    report = WheelReport(first_party=[f"{parse_wheel_filename(w.name)[0]}=={parse_wheel_filename(w.name)[1]}" for w in first_party])
    to_download: list[str] = []
    for item in resolved:
        name = normalize_name(item["metadata"]["name"])
        version = item["metadata"]["version"]
        pin = f"{name}=={version}"
        if name.startswith(RUNTIME_PROVIDED_PREFIXES):
            raise SystemExit(
                f"Bundle '{spec.name}' would ship {pin}: Fabric provides Spark; a bundled "
                "copy shadows the runtime's. Drop the requirement that pulls it in (the "
                "dbt-fabricspark[spark] extra exists only for machines without a Fabric "
                "runtime and never belongs in a bundle)."
            )
        if name in first_party_names:
            report.shipped.append(pin)
            continue
        runtime_version = runtime_pins.get(name)
        if runtime_version is not None and versions_equal(version, runtime_version):
            report.pruned.append(pin)
            continue
        if runtime_version is not None:
            override = override_names.get(name)
            if override is None:
                raise SystemExit(
                    f"Bundle '{spec.name}' resolved {pin} but runtime '{profile.version}' ships "
                    f"{runtime_version} and no override allows replacing it. This should be "
                    "impossible under the constraints file — is it stale? Re-run "
                    f"tools/refresh_runtime_constraints.py --runtime {profile.version}."
                )
            report.replaced[name] = {
                "runtime_version": runtime_version,
                "bundle_version": version,
                "specifier": override.specifier,
                "reason": override.reason,
            }
        report.shipped.append(pin)
        to_download.append(pin)

    if to_download:
        result = _pip([
            "download", "--no-deps", "--quiet", "--dest", str(wheels_dir),
            *target_args, *to_download,
        ])
        if result.returncode != 0:
            _fail(f"pip download of the '{spec.name}' wheels failed:", result)

    for wheel in wheels_dir.glob("*.whl"):
        if parse_wheel_filename(wheel.name)[0].startswith(RUNTIME_PROVIDED_PREFIXES):
            raise SystemExit(f"Fabric provides Spark; the bundle must not carry {wheel.name}.")

    report.shipped.sort()
    report.pruned.sort()
    (wheels_dir / "requirements.txt").write_text("\n".join(report.shipped) + "\n", encoding="utf-8")
    return wheels_dir, report, header


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------


def collect_tree(
    root: Path,
    *,
    prefix: str = "",
    excluded_dirs: Iterable[str] = (),
    excluded_files: Iterable[str] = (),
) -> list[tuple[Path, str]]:
    """(file, arcname) pairs for every file under ``root``, sorted, filtered."""
    excluded_dirs = set(excluded_dirs)
    excluded_files = set(excluded_files)
    entries: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in excluded_dirs for part in relative.parts):
            continue
        if path.is_file() and path.name not in excluded_files:
            entries.append((path, f"{prefix}{relative.as_posix()}"))
    return entries


def write_bundle(entries: Sequence[tuple[Path, str]], metadata: dict, wheels_dir: Path) -> tuple[bytes, int]:
    """Zip the code tree, deployment.json, bundle_bootstrap.py and wheels/.

    The embedded deployment.json is the runtime's source of truth for which
    build/commit the extracted code came from (the Files/ sidecar copy can lag
    the zip between the two upload requests).
    """
    reserved = {"deployment.json", BOOTSTRAP_ARCNAME}
    for _, arcname in entries:
        if arcname in reserved or arcname.startswith("wheels/"):
            raise SystemExit(f"Bundle tree must not contain {arcname}; the publisher adds it.")
    buffer = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in entries:
            archive.write(path, arcname)
            count += 1
        archive.writestr("deployment.json", json.dumps(metadata, indent=2))
        archive.write(BOOTSTRAP_SOURCE, BOOTSTRAP_ARCNAME)
        count += 1
        for wheel in sorted(wheels_dir.iterdir()):
            if wheel.is_file():
                archive.write(wheel, f"wheels/{wheel.name}")
                count += 1
    if not entries:
        raise SystemExit("No files collected for the bundle")
    return buffer.getvalue(), count


def git_commit_hash() -> str:
    try:
        return subprocess.run(  # noqa: S603, S607 — fixed argv
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


# ---------------------------------------------------------------------------
# OneLake
# ---------------------------------------------------------------------------


def build_credential():
    """Pick the least-interactive credential available.

    - CI/CD agents set the service principal env vars -> EnvironmentCredential.
    - Developers with the Azure CLI installed and logged in -> AzureCliCredential.
    - Otherwise: browser sign-in with a persistent token cache (DPAPI-encrypted
      on Windows), so the browser only opens on the first run.
    """
    from azure.identity import (
        AuthenticationRecord,
        AzureCliCredential,
        EnvironmentCredential,
        InteractiveBrowserCredential,
        TokenCachePersistenceOptions,
    )

    if all(os.environ.get(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")):
        print("  Auth: service principal (environment variables)")
        return EnvironmentCredential()

    if shutil.which("az"):
        credential = AzureCliCredential()
        try:
            credential.get_token(STORAGE_SCOPE)
            print("  Auth: Azure CLI")
            return credential
        except Exception:  # noqa: S110 — not logged in; fall through to browser sign-in
            pass

    # Windows encrypts the cache with DPAPI. On Linux/macOS without a keyring,
    # allow a plaintext cache: it holds refresh tokens for the signed-in
    # developer only (same trust boundary as the browser session).
    cache_options = TokenCachePersistenceOptions(
        name=PERSISTENT_CACHE_NAME, allow_unencrypted_storage=(sys.platform != "win32")
    )
    record = None
    if AUTH_RECORD_PATH.is_file():
        try:
            record = AuthenticationRecord.deserialize(AUTH_RECORD_PATH.read_text(encoding="utf-8"))
        except Exception:
            record = None

    credential = InteractiveBrowserCredential(
        cache_persistence_options=cache_options, authentication_record=record
    )
    if record is None:
        print("  Auth: no cached sign-in found - opening a browser window...")
        record = credential.authenticate(scopes=[STORAGE_SCOPE])
        AUTH_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTH_RECORD_PATH.write_text(record.serialize(), encoding="utf-8")
        print(f"  Auth: sign-in cached at {AUTH_RECORD_PATH}; future runs are silent")
    else:
        print(f"  Auth: cached browser sign-in ({record.username})")
    return credential


def lakehouse_files_prefix(lakehouse: str) -> str:
    """Name-based item paths need the .Lakehouse suffix; GUID-based ones must not."""
    if GUID_PATTERN.match(lakehouse):
        return f"{lakehouse}/Files"
    return f"{lakehouse}.Lakehouse/Files"


def upload_bundle(workspace: str, lakehouse: str, destination: str, payload: bytes, metadata: dict) -> None:
    from azure.storage.filedatalake import DataLakeServiceClient

    credential = build_credential()
    filesystem = DataLakeServiceClient(ONELAKE_URL, credential=credential).get_file_system_client(workspace)
    prefix = lakehouse_files_prefix(lakehouse)
    zip_path = f"{prefix}/{destination}"
    filesystem.get_file_client(zip_path).upload_data(payload, overwrite=True)
    print(f"  Uploaded: {zip_path}")
    # Sidecar copy for humans/monitoring; the zip-embedded copy is authoritative.
    metadata_path = f"{prefix}/{Path(destination).parent.as_posix()}/deployment.json"
    filesystem.get_file_client(metadata_path).upload_data(
        json.dumps(metadata, indent=2).encode("utf-8"), overwrite=True
    )
    print(f"  Uploaded: {metadata_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_common_args(parser: argparse.ArgumentParser, *, spec: BundleSpec, default_lakehouse: str) -> None:
    runtimes = "; ".join(f"{key}: {p.description or p.version}" for key, p in RUNTIME_PROFILES.items())
    parser.add_argument("--workspace", help="Fabric workspace name or GUID that contains the lakehouse.")
    parser.add_argument("--lakehouse", default=default_lakehouse, help=f"Lakehouse name or GUID (default: {default_lakehouse}).")
    parser.add_argument(
        "--destination", default=spec.default_destination,
        help=f"Target path under the lakehouse Files/ folder (default: {spec.default_destination}).",
    )
    parser.add_argument("--build-version", default="", help="Optional build/version label recorded in deployment.json.")
    parser.add_argument(
        "--runtime", default=spec.default_runtime, choices=sorted(RUNTIME_PROFILES),
        help=(
            f"Fabric runtime the wheels target (default: {spec.default_runtime}); must match the notebook "
            f"that installs the bundle. Profiles: {runtimes}."
        ),
    )
    parser.add_argument("--assemble-only", action="store_true", help="Resolve and build the zip without authenticating or uploading (CI).")
    parser.add_argument("--out", help="With --assemble-only: directory to write the zip and deployment.json into.")


def run(args: argparse.Namespace, spec: BundleSpec, entries: Callable[[], Sequence[tuple[Path, str]]], label: str) -> int:
    if not args.assemble_only and not args.workspace:
        raise SystemExit("--workspace is required unless --assemble-only is given.")

    profile = RUNTIME_PROFILES[args.runtime]

    print(f"{'Assembling' if args.assemble_only else 'Publishing'} {label} (bundle '{spec.name}')")
    print(f"  Runtime: {profile.version} (Python {profile.python_version}, {'/'.join(WHEEL_PLATFORMS)}) - {profile.description}")
    if spec.consumer:
        print(f"  Consumer: {spec.consumer}")
    if not args.assemble_only:
        print(f"  Workspace: {args.workspace}")
        print(f"  Lakehouse: {args.lakehouse}")

    metadata = {
        "project": spec.name,
        "consumer": spec.consumer,
        "build_version": args.build_version,
        "commit": git_commit_hash(),
        "published_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_version": profile.version,
        "runtime_description": profile.description,
        "wheel_python_version": profile.python_version,
        "wheel_platforms": list(WHEEL_PLATFORMS),
    }
    with tempfile.TemporaryDirectory(prefix=f"bundle-{spec.name}-") as tmp:
        wheels_dir, report, constraints = resolve_and_download(Path(tmp), spec, profile)
        metadata.update({
            "constraints_source": constraints,
            "wheel_requirements": report.shipped,
            "first_party": report.first_party,
            "overrides": report.replaced,
            "pruned_runtime_packages": report.pruned,
        })
        payload, count = write_bundle(list(entries()), metadata, wheels_dir)

    print(f"  Wheels shipped ({len(report.shipped)}): {', '.join(report.shipped)}")
    print(f"  Runtime-provided, pruned ({len(report.pruned)}): {', '.join(report.pruned) or '-'}")
    for name, details in report.replaced.items():
        print(
            f"  REPLACES runtime {name} {details['runtime_version']} -> {details['bundle_version']}: "
            f"{details['reason']}"
        )
    print(f"  Files in zip: {count} ({len(payload):,} bytes)")

    metadata = {**metadata, "file_count": count, "zip_bytes": len(payload)}
    if args.assemble_only:
        if args.out:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{spec.name}.zip").write_bytes(payload)
            (out / "deployment.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            print(f"  Written: {out / f'{spec.name}.zip'}")
        print(f"{label} assembled successfully (not uploaded).")
        return 0

    upload_bundle(args.workspace, args.lakehouse, args.destination, payload, metadata)
    print(f"{label} published successfully.")
    return 0
