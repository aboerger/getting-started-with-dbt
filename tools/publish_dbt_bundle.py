"""Publish a Jaffle Shop bundle — dbt project, dbt packages, adapters, runner — to OneLake.

Two notebooks run dbt on Fabric from a published zip instead of pulling GitHub
and PyPI at run time, and they run on different images, so there are two
bundles (``--runner``):

``--runner spark`` (default) -> ``Files/dbt/jaffle_shop.zip``
    For ``NB_dbt_Runner_Spark`` (PySpark notebook, Spark Runtime 2.0, Python
    3.13). Carries dbt-fabricspark only (``requirements/lakehouse.in``); dbt
    attaches to the notebook's Spark session (``method: session``).

``--runner python`` -> ``Files/dbt/jaffle_shop_python.zip``
    For ``NB_dbt_Runner`` (Python notebook, Python 3.11 kernel). Carries all
    three adapters (``requirements/warehouse.in`` + ``lakehouse.in`` +
    ``sqldb.in``, one resolve) so one notebook parameter picks the Warehouse,
    the Lakehouse over Livy or the SQL database.

Each zip holds:

- the dbt project (``jaffle_shop/``) with ``dbt_packages/`` vendored by running
  ``dbt deps`` first, so the notebook never talks to the dbt package hub;
- ``wheels/``: the adapters' dependency closure *minus everything the target
  runtime already ships*, plus a fresh ``jaffle-dbt-runner`` wheel from
  ``runner/`` — resolved against the runtime's package manifest by
  ``tools/onelake_bundle.py`` (manylinux wheels for the runtime's Python,
  offline install on the kernel);
- ``bundle_bootstrap.py`` (``tools/fabric_bundle_bootstrap.py``) and a
  ``deployment.json`` build stamp (commit, runtime, shipped/pruned/replaced wheels).

The adapter pins have one home each: ``requirements/<target>.in`` (the files
the laptop venvs are compiled from), so a bundle ships exactly the dbt-core and
adapters the laptop runs.

Why not ``pip install`` on the kernel at run time (what both notebooks did
before)? pip re-solves against whatever the runtime preinstalled and upgrades
shared packages in place; on Spark Runtime 2.0 dbt's ``protobuf`` requirement
lands on 6.33.x, which the runtime tolerates only up to 6.31.1 — sessions die
at kernel start with no useful error. On the Python notebook the upgrade of
azure-core landed on disk while the kernel kept the preinstalled 1.29.4 it had
already imported for notebookutils, so dbt-fabric's ``azure.identity`` import
failed. Resolving at publish time against the vendored runtime manifest turns
the first into a loud publish failure unless the replacement is allow-listed
in the runner's overrides with a reason; the bootstrap's module eviction
handles the second.

Usage (from ``.venv-tools``, see ``tools/setup-env.ps1``)::

    python tools/publish_dbt_bundle.py --workspace "<workspace name or GUID>"
    python tools/publish_dbt_bundle.py --runner python --workspace "<workspace name or GUID>"
    python tools/publish_dbt_bundle.py --assemble-only --out build/bundle   # CI: no upload

Without ``az`` or service-principal env vars the first publish opens a browser
sign-in and caches it for silent reuse. Requires network access to PyPI and the
dbt package hub at publish time — and none at run time. TLS trusts the operating
system's certificate store (``truststore``), so a corporate TLS-inspecting proxy
needs no ``REQUESTS_CA_BUNDLE`` juggling.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from onelake_bundle import (
    REPO_ROOT,
    BundleSpec,
    Override,
    add_common_args,
    collect_tree,
    read_requirements_in,
    run,
    use_os_trust_store,
)

PROJECT_DIR = REPO_ROOT / "jaffle_shop"
RUNNER_DIR = REPO_ROOT / "runner"
REQUIREMENTS_DIR = REPO_ROOT / "requirements"
DEFAULT_LAKEHOUSE = "LH_Jaffle_Shop"
# "wheels" so a stray local wheels/ folder inside the project dir can't
# double-ship next to the bundle the publisher adds at the zip root.
EXCLUDED_DIR_NAMES = {"target", "logs", "__pycache__", "wheels"}
EXCLUDED_FILE_NAMES = {".user.yml", ".gitignore"}


def merged_requirements(*targets: str) -> list[str]:
    """The union of ``requirements/<target>.in`` files, first occurrence wins.

    ``dbt-core~=1.11.0`` appears in every file; one resolve over the union is
    what guarantees the three adapters agree on a single dbt-core.
    """
    merged: list[str] = []
    for target in targets:
        for requirement in read_requirements_in(REQUIREMENTS_DIR / f"{target}.in"):
            if requirement not in merged:
                merged.append(requirement)
    return merged


# Runtime packages each bundle is allowed to replace. Each was found the hard
# way; each carries its reason so the next runtime update can re-check it.
SPARK_OVERRIDES = {
    "protobuf": Override(
        "==6.31.1",
        "dbt-core needs protobuf>=6,<7 and Runtime 2.0 ships 5.29.6; the runtime "
        "tolerates protobuf 6 only up to 6.31.1 (bisection 2026-09-03: 6.33.6 kills "
        "the kernel at startup, 6.31.1 works).",
    ),
    "opentelemetry-api": Override(
        "",
        "dbt-common needs opentelemetry-api>=1.26; Runtime 2.0 pins 1.16.0 via its "
        "opentelemetry-sdk. Validated harmless 2026-09-03 (dbt ran with api 1.44 "
        "installed alongside sdk 1.16).",
    ),
    "pathspec": Override(
        "",
        "dbt-core needs pathspec<0.13; Runtime 2.0 ships 1.1.1. Pure Python, only dbt "
        "imports it on this driver.",
    ),
}

PYTHON_OVERRIDES = {
    "azure-core": Override(
        "",
        "azure-identity 1.25.3 (dbt-fabric, dbt-fabricspark) imports AccessTokenInfo, "
        "which needs azure-core>=1.31; the Python-notebook image ships 1.29.4. This is "
        "the ImportError the old pip-at-run-time notebook died with (2026-09-09). The "
        "bootstrap evicts the pre-imported copy so dbt sees the bundle's.",
    ),
    "azure-identity": Override(
        "",
        "dbt-fabricspark needs azure-identity>=1.21 and dbt-fabric >=1.14; the image "
        "ships 1.17.1. Same eviction as azure-core.",
    ),
    "pyodbc": Override(
        "",
        "dbt-sqlserver needs pyodbc>=5.2; the image ships 4.0.39 (its ODBC Driver 18 is "
        "what both use). Compiled manylinux wheel; only dbt imports it in this kernel.",
    ),
}

SPECS: dict[str, BundleSpec] = {
    "spark": BundleSpec(
        name="jaffle_shop",
        default_runtime="2.0",  # the runtime the workspace's Spark settings select
        requirements=read_requirements_in(REQUIREMENTS_DIR / "lakehouse.in"),
        first_party_dirs=[RUNNER_DIR],
        overrides=SPARK_OVERRIDES,
        default_destination="dbt/jaffle_shop.zip",
        consumer="NB_dbt_Runner_Spark (PySpark notebook, target lakehouse_session)",
    ),
    "python": BundleSpec(
        name="jaffle_shop_python",
        default_runtime="python-3.11",  # the kernel NB_dbt_Runner's metadata names
        requirements=merged_requirements("warehouse", "lakehouse", "sqldb"),
        first_party_dirs=[RUNNER_DIR],
        overrides=PYTHON_OVERRIDES,
        default_destination="dbt/jaffle_shop_python.zip",
        consumer="NB_dbt_Runner (Python notebook, targets warehouse | lakehouse | sqldb)",
    ),
}
DEFAULT_RUNNER = "spark"


def parse_args(argv: Sequence[str] | None = None) -> tuple[argparse.Namespace, BundleSpec]:
    """``--runner`` picks the spec, and the spec supplies the other defaults."""
    runner_help = "Which notebook's bundle to build: " + "; ".join(
        f"{key} -> {spec.default_destination} for {spec.consumer}" for key, spec in SPECS.items()
    )
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--runner", choices=sorted(SPECS), default=DEFAULT_RUNNER)
    known, _ = pre.parse_known_args(argv)
    spec = SPECS[known.runner]

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runner", choices=sorted(SPECS), default=DEFAULT_RUNNER, help=runner_help)
    add_common_args(parser, spec=spec, default_lakehouse=DEFAULT_LAKEHOUSE)
    return parser.parse_args(argv), spec


def vendor_dbt_packages(project_dir: Path) -> None:
    """``dbt deps`` into the project so the zip carries ``dbt_packages/``.

    ``package-lock.yml`` is committed, so this is deterministic. Runs
    in-process through ``dbtRunner`` (not a subprocess) so the OS trust store
    injected by :func:`use_os_trust_store` covers the package-hub download. dbt
    must be importable in the publishing interpreter (it is in ``.venv-tools``).
    """
    if not any((project_dir / name).is_file() for name in ("packages.yml", "dependencies.yml")):
        return
    try:
        from dbt.cli.main import dbtRunner
    except ImportError as exc:
        raise SystemExit(
            "dbt is not importable here; run the publisher from .venv-tools "
            "(tools\\setup-env.ps1 -Target tools)."
        ) from exc
    res = dbtRunner().invoke(["deps", "--project-dir", str(project_dir), "--quiet"])
    if not res.success:
        raise SystemExit(f"dbt deps failed: {res.exception}")
    if not (project_dir / "dbt_packages").is_dir():
        raise SystemExit(f"dbt deps ran but {project_dir / 'dbt_packages'} does not exist.")
    print(f"  dbt packages vendored: {project_dir / 'dbt_packages'}")


def main(argv: Sequence[str] | None = None) -> int:
    args, spec = parse_args(argv)
    if not use_os_trust_store():
        print("  Note: truststore not installed; TLS trusts certifi only (set REQUESTS_CA_BUNDLE behind a proxy).")
    for required in ("dbt_project.yml", "profiles.yml"):
        if not (PROJECT_DIR / required).is_file():
            raise SystemExit(f"{required} not found under {PROJECT_DIR}")
    vendor_dbt_packages(PROJECT_DIR)

    def entries():
        return collect_tree(PROJECT_DIR, excluded_dirs=EXCLUDED_DIR_NAMES, excluded_files=EXCLUDED_FILE_NAMES)

    return run(args, spec, entries, label=f"Jaffle Shop dbt project from {PROJECT_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
