from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages" / "scheduler" / "src" / "smda_scheduler"
DEST = (
    ROOT
    / "plugins"
    / "smda-automation"
    / "runtime"
    / "python"
    / "smda_scheduler"
)
RUNNER_SOURCE = ROOT / "packages" / "sandcastle-runner" / "src" / "cli.ts"
RUNNER_DEST = (
    ROOT
    / "plugins"
    / "smda-automation"
    / "runtime"
    / "js"
    / "sandcastle-runner.mjs"
)


def main() -> int:
    sync_python_runtime()
    bundle_sandcastle_runner()
    return 0


def sync_python_runtime() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source package: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(
        SOURCE,
        DEST,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def bundle_sandcastle_runner() -> None:
    if not RUNNER_SOURCE.exists():
        raise SystemExit(f"missing runner source: {RUNNER_SOURCE}")
    esbuild = ROOT / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        raise SystemExit(f"missing esbuild: {esbuild}")
    RUNNER_DEST.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(esbuild),
            str(RUNNER_SOURCE),
            "--bundle",
            "--platform=node",
            "--format=esm",
            "--target=node20",
            f"--outfile={RUNNER_DEST}",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
