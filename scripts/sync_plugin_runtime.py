from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
    bundle_sandcastle_runner()
    return 0


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
