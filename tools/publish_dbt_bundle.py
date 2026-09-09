"""Publish the Jaffle Shop bundle — dbt project, dbt packages, dbt-fabricspark, runner — to OneLake.

``NB_dbt_Runner_Spark`` (PySpark notebook) runs dbt in-process on its own Spark
driver with dbt-fabricspark ``method: session``. Everything that notebook needs
arrives in one zip in the Lakehouse: ``Files/dbt/jaffle_shop.zip``. This script
builds and uploads it:

- the dbt project (``jaffle_shop/``) with ``dbt_packages/`` vendored by running
  ``dbt deps`` first, so the notebook never talks to the dbt package hub;
- ``wheels/``: dbt-fabricspark's dependency closure *minus everything Fabric
  Runtime 2.0 already ships*, plus a fresh ``jaffle-dbt-runner`` wheel from
  ``runner/`` — resolved against the runtime's package manifest by
  ``tools/onelake_bundle.py`` (cp313/manylinux, offline install on the driver);
- ``bundle_bootstrap.py`` (``tools/fabric_bundle_bootstrap.py``) and a
  ``deployment.json`` build stamp (commit, runtime, shipped/pruned/replaced wheels).

The adapter pin has one home: ``requirements/lakehouse.in`` (the same file the
laptop venv is compiled from), so the bundle ships exactly the dbt-core and
dbt-fabricspark the laptop runs.

Why not ``pip install`` on the driver at run time (what this notebook did
before)? pip re-solves against whatever the runtime preinstalled and silently
upgrades shared packages; on Fabric Runtime 2.0 dbt's ``protobuf`` requirement
lands on 6.33.x, which the runtime tolerates only up to 6.31.1 — sessions die
at kernel start with no useful error. Resolving at publish time against the
vendored runtime manifest turns that into a loud publish failure unless the
replacement is allow-listed in ``CONSTRAINT_OVERRIDES`` with a reason.

Usage (from ``.venv-tools``, see ``tools/setup-env.ps1``)::

    python tools/publish_dbt_bundle.py --workspace "<workspace name or GUID>"
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
REQUIREMENTS_IN = REPO_ROOT / "requirements" / "lakehouse.in"
# "wheels" so a stray local wheels/ folder inside the project dir can't
# double-ship next to the bundle the publisher adds at the zip root.
EXCLUDED_DIR_NAMES = {"target", "logs", "__pycache__", "wheels"}
EXCLUDED_FILE_NAMES = {".user.yml", ".gitignore"}

# dbt-core + dbt-fabricspark, exactly as the laptop venv pins them.
WHEEL_REQUIREMENTS = read_requirements_in(REQUIREMENTS_IN)

# Runtime packages this bundle is allowed to replace. Each was found the hard
# way; each carries its reason so the next runtime update can re-check it.
CONSTRAINT_OVERRIDES = {
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

SPEC = BundleSpec(
    name="jaffle_shop",
    default_runtime="2.0",  # the runtime the workspace's Spark settings select
    requirements=WHEEL_REQUIREMENTS,
    first_party_dirs=[RUNNER_DIR],
    overrides=CONSTRAINT_OVERRIDES,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(
        parser, spec=SPEC,
        default_lakehouse="LH_Jaffle_Shop",
        default_destination="dbt/jaffle_shop.zip",
    )
    return parser.parse_args()


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


def main() -> int:
    args = parse_args()
    if not use_os_trust_store():
        print("  Note: truststore not installed; TLS trusts certifi only (set REQUESTS_CA_BUNDLE behind a proxy).")
    for required in ("dbt_project.yml", "profiles.yml"):
        if not (PROJECT_DIR / required).is_file():
            raise SystemExit(f"{required} not found under {PROJECT_DIR}")
    vendor_dbt_packages(PROJECT_DIR)

    def entries():
        return collect_tree(PROJECT_DIR, excluded_dirs=EXCLUDED_DIR_NAMES, excluded_files=EXCLUDED_FILE_NAMES)

    return run(args, SPEC, entries, label=f"Jaffle Shop dbt project from {PROJECT_DIR.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
