import os
from pathlib import Path

from packr.core import (
    minimum_dependency_set,
    parse_file_imports,
    parse_package_imports,
    read_code,
)


def test_parse_file_imports():
    fpath = Path(os.getcwd()) / "tests/core_package/main.py"
    fpath = str(fpath)
    code = read_code(fpath)
    imports = parse_file_imports(fpath, code)

    assert len(imports) == 3


def test_parse_package_imports():
    fpath = str(Path(os.getcwd()) / "tests/main_project")

    imported_modules, user_modules = parse_package_imports(fpath, ignores=["tests"])
    assert imported_modules
    assert user_modules


def test_minimum_dependency_set():
    main_path = str(Path(os.getcwd()) / "tests/main_project")
    core_path = str(Path(os.getcwd()) / "tests/core_package")
    min_deps = minimum_dependency_set(
        main_path,
        core_path,
    )

    assert min_deps == set(
        ["thirdpartydep1", "thirdpartydep5", "thirdpartydep6", "thirdpartydep8"]
    )
