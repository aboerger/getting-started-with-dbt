"""Regenerate the vendored pip constraints file for a Fabric notebook runtime.

Microsoft publishes each runtime's base Python environment in
github.com/microsoft/synapse-spark-runtime, in two shapes:

* **Spark runtimes** (``manifest_format="conda-yml"``): one conda environment
  YML per runtime, e.g. ``Runtime 2.0 (Spark 4.1)/Fabric-Python313-CPU.yml``.
* **Python notebooks** (``manifest_format="release-markdown"``): the
  ``Jupyter 1.0`` folder holds one release note per image build, a markdown
  file with a package table per kernel (``# Python3.10`` / ``# Python3.11`` /
  ``# Python3.12``). Upgraded entries read ``old ⬆️ new``; the *new* version is
  the one the release ships, so that is what the constraints record. The file
  name carries the release date, so the profile points at the folder (GitHub
  contents API) and the newest ``.md`` is picked at refresh time.

This script turns either into a pip constraints file (``name==version`` per
package) under ``tools/runtime_constraints/``. The publish script passes it to
``pip install --dry-run -c`` so a bundle is resolved *against what the runtime
already ships*: any requirement that would force a runtime package to a
different version fails the publish, loudly, at build time — unless it is
explicitly allow-listed with a reason in that script's overrides. Wheels
that resolve to the runtime's own version are then pruned from the bundle.

That is the failure mode we want. ``pip check`` only ever sees *declared*
conflicts (in the incident this tooling comes from it named opentelemetry and
missed the protobuf upgrade that killed the Spark kernel); comparing against
the manifest catches what actually gets replaced. The Python-notebook runner
hit the same class of problem from the other side: ``pip install`` of dbt on
the driver upgraded azure-core on disk while the kernel kept the preinstalled
1.29.4 it had already imported, and dbt-fabric's ``azure.identity`` import
failed.

Run by a human whenever a runtime update lands (the header records the
manifest hash, so re-running is a no-op until Microsoft changes the file)::

    python tools/refresh_runtime_constraints.py --runtime 2.0
    python tools/refresh_runtime_constraints.py --runtime python-3.11

Conda-to-PyPI mapping is deliberately simple: names are normalized (PEP 503),
a few known renames are mapped, versions that are not valid PEP 440 (system
libraries with conda-style versions) and OS-level packages are skipped. Pip
ignores constraints for names not in a resolve, so over-inclusion is harmless;
a *missing* mapping merely means that package is not gated (and, if it lands
in a bundle, shows up in the publish report as a replacement).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

from onelake_bundle import CONSTRAINTS_DIR, RUNTIME_PROFILES, RuntimeProfile, normalize_name, use_os_trust_store

# Conda package names whose PyPI project is spelled differently.
CONDA_TO_PYPI = {
    "msgpack-python": "msgpack",
    "matplotlib-base": "matplotlib",
    "pytables": "tables",
    "python-graphviz": "graphviz",
    "importlib_metadata": "importlib-metadata",
    "typing_extensions": "typing-extensions",
    "prompt_toolkit": "prompt-toolkit",
}

# Conda entries that are not Python distributions (or collide with a PyPI
# project of the same name but different meaning/versioning — tzdata is the
# IANA database in conda, a Python package on PyPI).
SKIP_NAMES = {
    "python", "pip", "setuptools", "wheel", "ca-certificates", "certifi-system",
    "openssl", "sqlite", "zlib", "ncurses", "readline", "bzip2", "xz", "tk", "tzdata",
    "expat", "libffi", "ld_impl_linux-64", "icu", "krb5", "libuuid", "libnsl",
    "libxcrypt", "python_abi", "nodejs", "openjdk", "r-base", "_libgcc_mutex",
    "_openmp_mutex", "brotli-bin", "gmp", "mpfr", "mpc", "pcre2", "yaml",
}

# PEP 440-ish sanity check; conda versions like "2025c" or "1.1.1w" fail it.
PEP440 = re.compile(
    r"^v?\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[0-9A-Za-z.]+)?$"
)

CONDA_LINE = re.compile(r"^\s*-\s*([A-Za-z0-9_.\-]+)=([^=\s]+)(=\S+)?\s*$")
PIP_LINE = re.compile(r"^\s*-\s*([A-Za-z0-9_.\-]+)==(\S+)\s*$")
MARKDOWN_HEADING = re.compile(r"^#\s+(.*?)\s*$")
UPGRADE_ARROW = "⬆"  # ⬆ (the release notes add a variation selector after it)


def _accept(raw_name: str, version: str, pins: dict[str, str]) -> None:
    if raw_name.startswith(("lib", "_")) or raw_name in SKIP_NAMES:
        return
    name = normalize_name(CONDA_TO_PYPI.get(raw_name, raw_name))
    if name in SKIP_NAMES or not PEP440.match(version):
        return
    pins[name] = version


def parse_manifest(text: str) -> dict[str, str]:
    """Return {normalized pypi name: version} from a Fabric Spark runtime conda YML."""
    pins: dict[str, str] = {}
    for line in text.splitlines():
        match = PIP_LINE.match(line) or CONDA_LINE.match(line)
        if not match:
            continue
        _accept(match.group(1), match.group(2), pins)
    return pins


def _release_version(cell: str) -> str:
    """``**5.29.3 ⬆️ 6.33.6**`` -> ``6.33.6``; plain cells unchanged."""
    cell = cell.replace("**", "").strip()
    if UPGRADE_ARROW in cell:
        cell = cell.split(UPGRADE_ARROW, 1)[1]
    return cell.replace("️", "").strip()


def parse_release_markdown(text: str, section: str) -> dict[str, str]:
    """Return {normalized pypi name: version} from one kernel's table in a
    Python-notebook release note (``# Python3.11`` etc.).

    Rows carry two name/version pairs (``|name|version|name|version|``);
    upgraded entries are bold with ``old ⬆️ new`` and resolve to ``new``.
    """
    pins: dict[str, str] = {}
    in_section = False
    for line in text.splitlines():
        heading = MARKDOWN_HEADING.match(line)
        if heading:
            in_section = heading.group(1).replace(" ", "").lower() == section.replace(" ", "").lower()
            continue
        if not in_section or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set("".join(cells)) <= set("-: "):
            continue  # separator row
        for i in range(0, len(cells) - 1, 2):
            name = cells[i].replace("**", "").strip()
            version = _release_version(cells[i + 1])
            if not name or name.lower() == "name" or not version:
                continue
            _accept(name, version, pins)
    if not pins:
        raise SystemExit(f"No package table found under heading '# {section}' - format changed?")
    return pins


def newest_release_note(index_json: str, index_url: str) -> str:
    """Pick the newest ``.md`` in a GitHub contents-API folder listing.

    Release notes are named ``...-Rel-<YYYY-MM-DD>.<n>-rc.<m>.md``, so the
    lexically greatest name is the latest release.
    """
    entries = json.loads(index_json)
    names = sorted(e["name"] for e in entries if e.get("type") == "file" and e["name"].endswith(".md"))
    if not names:
        raise SystemExit(f"No .md release note found in {index_url}")
    download = next(e["download_url"] for e in entries if e["name"] == names[-1])
    return download


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "getting-started-with-dbt/refresh-constraints"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 — fixed https URL
        return response.read().decode("utf-8")


def resolve_manifest(profile: RuntimeProfile, manifest_file: str | None) -> tuple[str, str]:
    """Return (manifest text, source URL or path)."""
    if manifest_file:
        return Path(manifest_file).read_text(encoding="utf-8"), manifest_file
    url = profile.manifest_url
    if profile.manifest_is_index:
        url = newest_release_note(fetch_text(url), url)
    return fetch_text(url), url


def parse_for_profile(profile: RuntimeProfile, text: str) -> dict[str, str]:
    if profile.manifest_format == "release-markdown":
        return parse_release_markdown(text, profile.manifest_section)
    if profile.manifest_format == "conda-yml":
        return parse_manifest(text)
    raise SystemExit(f"Unknown manifest_format {profile.manifest_format!r} on runtime profile {profile.version}")


def render(profile: RuntimeProfile, source_url: str, digest: str, pins: dict[str, str]) -> str:
    header = [
        f"# Fabric runtime '{profile.version}' ({profile.description}) base Python packages, as pip constraints.",
        "# GENERATED by tools/refresh_runtime_constraints.py — do not edit by hand.",
        f"# source: {source_url}",
        f"# manifest_sha256: {digest}",
    ]
    if profile.manifest_section:
        header.append(f"# manifest_section: {profile.manifest_section}")
    header += [
        "# Consumed by tools/onelake_bundle.py (pip install --dry-run -c) so a bundle can",
        "# never replace a runtime package without an explicit override entry in the",
        "# publish script.",
        "",
    ]
    body = [f"{name}=={version}" for name, version in sorted(pins.items())]
    return "\n".join(header + body) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", required=True, choices=sorted(RUNTIME_PROFILES))
    parser.add_argument(
        "--manifest-file",
        help="Read the manifest from a local file instead of fetching it (tests, offline).",
    )
    args = parser.parse_args()
    profile = RUNTIME_PROFILES[args.runtime]

    use_os_trust_store()  # corporate proxy CA lives in the OS store, not certifi
    text, source = resolve_manifest(profile, args.manifest_file)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    pins = parse_for_profile(profile, text)
    if len(pins) < 50:
        raise SystemExit(f"Only {len(pins)} packages parsed from the manifest — format changed?")

    target = CONSTRAINTS_DIR / profile.constraints_file
    content = render(profile, source, digest, pins)
    if target.is_file() and target.read_text(encoding="utf-8") == content:
        print(f"{target.relative_to(CONSTRAINTS_DIR.parent.parent)}: unchanged ({len(pins)} packages)")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"{target.relative_to(CONSTRAINTS_DIR.parent.parent)}: written ({len(pins)} packages) from {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
