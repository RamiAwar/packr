import collections
import os
from itertools import dropwhile
from logging import getLogger
from pathlib import Path, PurePath
from typing import Any, Dict, List, Set

import nbformat

from packr.imports_parser import ImportsParser

logger = getLogger("main")


class udeque(collections.deque):
    """Unique deque that only appends elements if they don't already exist in the deque"""

    def append(self, x: Any):
        if x in self:
            return
        return super().append(x)


def trim_suffix(content, suffix):
    if content.endswith(suffix):
        return content[: -len(suffix)]
    return content


def read_code(fpath):
    if fpath.endswith(".ipynb"):
        nb = nbformat.read(fpath, as_version=4)
        code = ""
        for cell in nb.cells:
            if cell.cell_type == "code":
                code += cell.source + "\n"
        return code
    elif fpath.endswith(".py"):
        with open(fpath, "rb") as f:
            return f.read()
    return None


def parse_file_imports(fpath, content):
    py_codes = collections.deque([(content, 1)])
    parser = ImportsParser(lambda code, lineno: py_codes.append((code, lineno)))  # noqa

    while py_codes:
        code, lineno = py_codes.popleft()
        try:
            parser.parse(code, fpath, lineno)
        except SyntaxError as e:
            # Ignore SyntaxError in Python code.
            logger.warn("parse %s:%d failed: %r", fpath, lineno, e)
    return parser.modules


def parse_package_imports(package_root, ignores=None):
    ignores = set(ignores) if ignores else set()
    ignores |= set(
        [
            ".hg",
            ".svn",
            ".git",
            ".pytest_cache",
            ".vscode",
            "__pycache__",
            ".venv",
            "venv",
            ".env",
            ".history",
        ]
    )

    imported_modules = []
    user_modules = set()

    for dirpath, dirnames, files in os.walk(
        package_root, topdown=True, followlinks=True
    ):
        dirnames[:] = [d for d in dirnames if d not in ignores]
        has_py = False
        for fn in files:
            fpath = os.path.join(dirpath, fn)
            # C extension
            if fn.endswith(".so"):
                has_py = True
                user_modules.add(fpath)
            # Normal Python file.
            elif fn.endswith(".py"):
                has_py = True
                user_modules.add(fpath)
            code = read_code(fpath)
            if code:
                imports = parse_file_imports(fpath, code)
                imported_modules.extend(imports)
        if has_py:
            user_modules.add(trim_suffix(dirpath, "/"))
    return imported_modules, user_modules


def import_extractor(path: str, package_name: str):
    """Extracts python import path from file system path

        For example:
        '/Users/bob/code/core_package/utils' with package_name=core_package
        becomes 'core_package.utils'

    Args:
        path (str): Path to python file
        package_name (str): Name of package to look for in the path

    """
    parts = PurePath(path).parts
    # parts = parts + tuple(Path(path).suffix)
    # TODO: Add special case for __init__

    # Discard first value if repeated package name
    parts = list(dropwhile(lambda part: part != package_name, parts))

    if len(parts) > 1 and parts[0] == parts[1]:
        parts = parts[1:]

    return parts


def minimum_dependency_set(
    main_module_path: str,
    core_module_path: str,
    main_module_name: str = None,
    core_module_name: str = None,
):
    """_summary_

    Args:
        main_module_path (str): Path to main project/package
        core_module_path (str): Path to depended package
        core_module_name (str, optional): _description_. Defaults to None.
    """
    # Find main and core module dependencies
    main_imported_modules, main_user_modules = parse_package_imports(
        main_module_path, ignores=["tests"]
    )
    core_imported_modules, core_user_modules = parse_package_imports(
        core_module_path, ignores=["tests"]
    )

    if not core_module_name:
        core_module_name = str(Path(core_module_path).stem)

    if not main_module_name:
        main_module_name = str(Path(main_module_path).stem)

    # Create maps of file -> set of deps
    main_modules: Dict[str, Set[str]] = collections.defaultdict(set)
    for module in main_imported_modules:
        # If module is a high level package, try to add alias to find more specific module
        if any(
            str(Path(*module.name.split("."), module.alias)) in m
            for m in main_user_modules
        ):
            main_modules[module.file].add(module.name + "." + module.alias)
        else:
            main_modules[module.file].add(module.name)

    core_modules: Dict[str, Set[str]] = collections.defaultdict(set)
    for module in core_imported_modules:
        # If module is a high level package, try to add alias to find more specific module
        if any(
            str(Path(*module.name.split("."), module.alias)) in m
            for m in core_user_modules
        ):
            core_modules[module.file].add(module.name + "." + module.alias)
        else:
            core_modules[module.file].add(module.name)

    # Import path -> path map for core package
    core_import_to_path_map = {
        ".".join(import_extractor(path[:-3], core_module_name)): path
        for path in core_user_modules
    }

    core_user_import_names: List[str] = [
        ".".join(import_extractor(path[:-3], core_module_name))
        for path in core_user_modules
    ]

    # Find all files used from core_package
    necessary_files = udeque()
    for file, modules in main_modules.items():
        for module in modules:
            # Check if module is part of core module first
            if module in core_import_to_path_map:
                necessary_files.append(core_import_to_path_map[module])

    # Find necessary imports
    necessary_imports = set()
    visited_files = set()

    while necessary_files:
        f = necessary_files.popleft()
        visited_files.add(f)

        modules = udeque(core_modules[f])
        visited = set()

        while modules:
            module = modules.popleft()
            if module in visited:
                continue

            visited.add(module)

            if module in core_user_import_names:
                file = core_import_to_path_map[module]
                if file not in visited_files:
                    necessary_files.append(file)

            elif module.startswith(core_module_name):
                # This is probably a package import (not specific file)
                # Need to import all subfiles/packages in this case
                for m in core_user_import_names:
                    if m.startswith(module):
                        modules.append(m)
            else:
                # If third party module, specify main package name only
                necessary_imports.add(module)

    return necessary_imports
