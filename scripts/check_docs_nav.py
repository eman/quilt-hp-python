#!/usr/bin/env python3
"""Validate MkDocs nav/file consistency for docs quality gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _make_loader() -> type[yaml.SafeLoader]:
    """Return a SafeLoader that silently ignores !!python/name: tags (used by mkdocs-material)."""
    loader = yaml.SafeLoader

    def _ignore_python_tag(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> str:
        return loader.construct_scalar(node)  # type: ignore[arg-type]

    loader.add_multi_constructor("tag:yaml.org,2002:python/", _ignore_python_tag)
    return loader
DOCS_DIR = ROOT / "docs"
MKDOCS_CONFIG = ROOT / "mkdocs.yml"


def _collect_nav_doc_paths(node: Any) -> set[Path]:
    paths: set[Path] = set()
    if isinstance(node, str):
        if node.endswith(".md") and not node.startswith(("http://", "https://")):
            paths.add(Path(node))
        return paths
    if isinstance(node, list):
        for item in node:
            paths.update(_collect_nav_doc_paths(item))
        return paths
    if isinstance(node, dict):
        for value in node.values():
            paths.update(_collect_nav_doc_paths(value))
        return paths
    return paths


def main() -> int:
    config = yaml.load(MKDOCS_CONFIG.read_text(encoding="utf-8"), Loader=_make_loader())
    nav_paths = _collect_nav_doc_paths(config.get("nav", []))

    missing_in_docs = sorted(path for path in nav_paths if not (DOCS_DIR / path).is_file())

    docs_paths = {
        path.relative_to(DOCS_DIR)
        for path in DOCS_DIR.rglob("*.md")
        if path.is_file()
    }
    missing_in_nav = sorted(path for path in docs_paths if path not in nav_paths)

    errors: list[str] = []
    if missing_in_docs:
        errors.append("Nav references missing markdown files:")
        errors.extend(f"  - docs/{path.as_posix()}" for path in missing_in_docs)
    if missing_in_nav:
        errors.append("Markdown files exist under docs/ but are missing from mkdocs nav:")
        errors.extend(f"  - docs/{path.as_posix()}" for path in missing_in_nav)

    if errors:
        print("\n".join(errors))
        return 1

    print(f"Docs nav check passed ({len(nav_paths)} nav markdown pages, {len(docs_paths)} docs files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
