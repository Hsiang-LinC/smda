from __future__ import annotations

import shutil
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


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source package: {SOURCE}")
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(
        SOURCE,
        DEST,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
