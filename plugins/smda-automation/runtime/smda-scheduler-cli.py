from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_RUNTIME = Path(__file__).resolve().parent / "python"
sys.path.insert(0, str(PLUGIN_RUNTIME))

from smda_scheduler.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
