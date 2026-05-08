# Contributing

Contributions are welcome. This page covers everything you need to set up a development environment, run the test and lint suite, and submit a pull request.

---

## Prerequisites

- Python 3.11+
- `git`
- A Quilt account with at least one system (for integration tests)

---

## Clone and set up

```bash
git clone https://github.com/eman/quilt-hp-python.git
cd quilt-hp-python

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows

# Install all dependencies including dev extras
pip install -e ".[dev]"
```

The `[dev]` extra installs `pytest`, `pytest-asyncio`, `mypy`, `ruff`, and `mkdocs-material`.

---

## Running the checks

```bash
# Run the linter (ruff)
ruff check src/ tests/

# Run the type checker (mypy)
mypy src/

# Run the test suite
pytest

# Build the docs locally
python -m mkdocs serve
```

All four commands must pass before a PR can be merged.

---

## Project structure

```
quilt-hp-python/
├── src/
│   └── quilt_hp/
│       ├── __init__.py          # public exports
│       ├── client.py            # QuiltClient façade
│       ├── auth.py              # authenticate()
│       ├── tokens.py            # token protocols and CachedTokens
│       ├── transport.py         # gRPC channel, _AuthInterceptor
│       ├── const.py             # constants (Environment, Cognito IDs)
│       ├── exceptions.py        # QuiltError hierarchy
│       ├── models/              # dataclass models
│       ├── services/            # gRPC service wrappers
│       ├── proto/               # vendored generated stubs
│       └── cli/                 # CLI entry point
├── tests/
├── docs/
├── scripts/
│   └── regen_protos.sh          # proto regeneration
├── mkdocs.yml
└── pyproject.toml
```

---

## Pull request process

1. Create a branch from `main`: `git checkout -b feature/my-change`.
2. Make your changes. Add or update tests as appropriate.
3. Run all checks: linter, type checker, tests, docs build.
4. Commit with a descriptive message.
5. Push and open a pull request against `main`.
6. Describe what changed and why in the PR description.

All PRs require at least one passing CI run. The CI pipeline runs the same four commands listed above.

---

## Commit message conventions

Use present-tense imperative subject lines:

```
Add support for DeclaredUserType in patch_user_attributes
Fix token expiry buffer calculation
Update streaming protocol documentation
```

Keep the first line under 72 characters. Add a blank line and a longer description for non-trivial changes.

---

## Quality gates

| Gate | Tool | Must pass |
|------|------|-----------|
| Linting | ruff | Yes |
| Type checking | mypy | Yes |
| Tests | pytest | Yes |
| Docs build | mkdocs build --strict | Yes |
| Proto stubs up-to-date | check_docs_nav.py | Yes |

---

## Asking for help

Open a GitHub issue for bugs or unexpected behavior. For discussion about design or new features, start a GitHub Discussion.
