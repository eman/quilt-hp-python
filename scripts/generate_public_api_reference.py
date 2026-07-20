#!/usr/bin/env python3
"""Generate markdown API reference for public quilt_hp symbols."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "python-api" / "public-api-reference.md"


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _format_signature(obj: Any) -> str:
    try:
        return str(inspect.signature(obj))
    except (TypeError, ValueError):
        return "()"


def _module_names() -> list[str]:
    names = ["quilt_hp"]
    pkg = importlib.import_module("quilt_hp")
    for mod in pkgutil.walk_packages(pkg.__path__, f"{pkg.__name__}."):
        if mod.name.startswith("quilt_hp._proto"):
            continue
        if mod.name.startswith("quilt_hp.cli"):
            continue
        names.append(mod.name)
    return sorted(set(names))


def _module_functions(module: Any) -> list[tuple[str, Any]]:
    funcs: list[tuple[str, Any]] = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not _is_public(name):
            continue
        if obj.__module__ != module.__name__:
            continue
        funcs.append((name, obj))
    return funcs


def _class_methods(cls: type[Any]) -> list[tuple[str, Any]]:
    methods: list[tuple[str, Any]] = []
    for name, member in cls.__dict__.items():
        if not _is_public(name):
            continue
        if isinstance(member, (classmethod, staticmethod)):
            methods.append((name, member.__func__))
            continue
        if isinstance(member, property):
            methods.append((name, member))
            continue
        if inspect.isfunction(member) or inspect.ismethoddescriptor(member):
            methods.append((name, member))
    return sorted(methods, key=lambda item: item[0])


def _module_classes(module: Any) -> list[tuple[str, type[Any]]]:
    classes: list[tuple[str, type[Any]]] = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if not _is_public(name):
            continue
        if obj.__module__ != module.__name__:
            continue
        classes.append((name, obj))
    return classes


def main() -> None:
    lines: list[str] = [
        "# Public API reference",
        "",
        "This page is generated from `src/quilt_hp` by",
        "`scripts/generate_public_api_reference.py`.",
        "",
        "It documents public modules, classes, methods, and functions with",
        "their Python signatures.",
        "",
    ]

    for module_name in _module_names():
        module = importlib.import_module(module_name)
        lines.extend([f"## `{module_name}`", ""])

        if module_name == "quilt_hp":
            exports = getattr(module, "__all__", [])
            if exports:
                lines.extend(["### Exports", ""])
                for name in exports:
                    obj = getattr(module, name, None)
                    if inspect.isclass(obj):
                        lines.append(f"- `{name}{_format_signature(obj)}` *(class)*")
                    elif inspect.isfunction(obj):
                        lines.append(f"- `{name}{_format_signature(obj)}` *(function)*")
                    else:
                        lines.append(f"- `{name}`")
                lines.append("")

        functions = _module_functions(module)
        if functions:
            lines.extend(["### Functions", ""])
            for name, func in functions:
                lines.append(f"- `{name}{_format_signature(func)}`")
            lines.append("")

        classes = _module_classes(module)
        if classes:
            lines.extend(["### Classes", ""])
            for class_name, cls in classes:
                lines.append(f"#### `{class_name}`")
                lines.append("")

                if "__init__" in cls.__dict__:
                    init = cls.__dict__["__init__"]
                    lines.append(f"- `__init__{_format_signature(init)}`")

                for method_name, method in _class_methods(cls):
                    if method_name == "__init__":
                        continue
                    if isinstance(method, property):
                        lines.append(f"- `{method_name}` *(property)*")
                    else:
                        lines.append(
                            f"- `{method_name}{_format_signature(method)}`",
                        )
                lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
