import tomllib
from pathlib import Path


def test_pyproject_exposes_smda_scheduler_console_script():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["smda-scheduler"] == (
        "smda_scheduler.cli:main"
    )


def test_pyproject_declares_scheduler_src_layout():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {
        "": "packages/scheduler/src"
    }
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == [
        "packages/scheduler/src"
    ]
