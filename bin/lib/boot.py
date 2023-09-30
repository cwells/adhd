"""
This module must not import any optional dependencies, nor import from elsewhere in lib/.
"""

import importlib
import shutil


def missing_modules(required: dict[str, str]) -> list[str]:
    missing: list[str] = []

    for req in required:
        try:
            importlib.import_module(req)
        except ModuleNotFoundError:
            # return the package name, not module name
            missing.append(required[req])

    return missing


def missing_binaries(required: list[str]) -> list[str]:
    missing: list[str] = []

    for req in required:
        path = shutil.which(req)
        if path is None:
            missing.append(req)

    return missing
