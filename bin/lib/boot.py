"""
This module must not import any optional dependencies, nor import from elsewhere in lib/.
"""

import importlib


def missing_modules(required: list[str]) -> list[str]:
    missing: list[str] = []

    for req in required:
        try:
            importlib.import_module(req)
        except ModuleNotFoundError:
            missing.append(req)

    return missing
