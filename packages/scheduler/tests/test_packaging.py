import tomllib
from pathlib import Path


def test_pyproject_exposes_smda_scheduler_console_script():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["smda-scheduler"] == (
        "smda_scheduler.cli:main"
    )
