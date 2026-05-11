#!/usr/bin/env python3
"""Bump the project version across all relevant files.

Usage:
    python scripts/bump_version.py --patch        # 0.1.0 → 0.1.1
    python scripts/bump_version.py --minor        # 0.1.0 → 0.2.0
    python scripts/bump_version.py --major        # 0.1.0 → 1.0.0
    python scripts/bump_version.py --version 0.3.0
"""

import argparse
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_TARGETS = [
    (
        ROOT / "pyproject.toml",
        re.compile(r'(?P<pre>^version\s*=\s*")(?P<version>\d+\.\d+\.\d+)(?P<post>")', re.MULTILINE),
    ),
    (
        ROOT / "src/quilt_hp/__init__.py",
        re.compile(r'(?P<pre>^__version__\s*=\s*")(?P<version>\d+\.\d+\.\d+)(?P<post>")', re.MULTILINE),
    ),
    (
        ROOT / "docs/reference/client.md",
        re.compile(r'(?P<pre>__version__:\s*str\s*#\s*e\.g\.\s*")(?P<version>\d+\.\d+\.\d+)(?P<post>")'),
    ),
    (
        ROOT / "tests/test_cli_surfaces_extra.py",
        re.compile(r'(?P<pre>result\.stdout\.strip\(\)\s*==\s*")(?P<version>\d+\.\d+\.\d+)(?P<post>")'),
    ),
]

CHANGELOG = ROOT / "CHANGELOG.md"


def current_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    if not m:
        raise SystemExit("ERROR: Could not find version in pyproject.toml")
    return m.group(1)


def next_semver(version: str, part: str) -> str:
    major, minor, patch = map(int, version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def update_files(new: str) -> None:
    replacement = rf"\g<pre>{new}\g<post>"
    for path, pattern in VERSION_TARGETS:
        text = path.read_text(encoding="utf-8")
        updated, count = pattern.subn(replacement, text)
        if count == 0:
            print(f"  SKIP     {path.relative_to(ROOT)}  (version string not found)")
            continue
        path.write_text(updated, encoding="utf-8")
        print(f"  updated  {path.relative_to(ROOT)}  ({count} occurrence{'s' if count > 1 else ''})")


def update_changelog(old: str, new: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    today = date.today().isoformat()
    new_header = f"## [{new}] - {today}"

    if "## [Unreleased]" in text:
        # Promote [Unreleased] → [new version] and add a fresh empty [Unreleased]
        updated = text.replace("## [Unreleased]", f"## [Unreleased]\n\n{new_header}", 1)
    else:
        # No [Unreleased] section — insert one plus new version stub before first ## [x.y.z]
        m = re.search(r"^## \[\d", text, re.MULTILINE)
        if m:
            pos = m.start()
            updated = text[:pos] + f"## [Unreleased]\n\n{new_header}\n\n" + text[pos:]
        else:
            updated = text + f"\n## [Unreleased]\n\n{new_header}\n"

    CHANGELOG.write_text(updated, encoding="utf-8")
    print(f"  updated  CHANGELOG.md  →  added {new_header}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bump the project version across all relevant files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--major", action="store_true", help="Bump major version (x.0.0)")
    group.add_argument("--minor", action="store_true", help="Bump minor version (x.y.0)")
    group.add_argument("--patch", action="store_true", help="Bump patch version (x.y.z+1)")
    group.add_argument("--version", metavar="X.Y.Z", help="Set an explicit version")
    args = parser.parse_args()

    old = current_version()

    if args.version:
        new = args.version
    elif args.major:
        new = next_semver(old, "major")
    elif args.minor:
        new = next_semver(old, "minor")
    else:
        new = next_semver(old, "patch")

    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        raise SystemExit(f"ERROR: Invalid version '{new}' — must be X.Y.Z")
    if new == old:
        raise SystemExit(f"ERROR: New version is the same as current ({old})")

    print(f"Bumping {old} → {new}\n")
    update_files(new)
    update_changelog(old, new)
    print("\nNext steps:")
    print(f"  1. Fill in the ## [{new}] section in CHANGELOG.md")
    print(f"  2. git add -A && git commit -m 'chore: bump version to {new}'")
    print(f"  3. git tag v{new} && git push origin main v{new}")


if __name__ == "__main__":
    main()
