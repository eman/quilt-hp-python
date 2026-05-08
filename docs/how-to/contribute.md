# Contribute to the project

This guide covers how to set up a development environment, run the check suite, submit a pull request, and keep documentation in sync with code changes.

---

## Set up a development environment

1. Clone the repository:

   ```bash
   git clone https://github.com/eman/quilt-hp-python.git
   cd quilt-hp-python
   ```

2. Create a virtual environment and install all dev dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # or .venv\Scripts\activate on Windows
   pip install -e ".[dev]"
   ```

   The `[dev]` extra installs `pytest`, `pytest-asyncio`, `mypy`, `ruff`, and `mkdocs-material`.

---

## Run the full check suite

Before opening a pull request, all four checks must pass:

```bash
# Linter
ruff check src/ tests/

# Type checker
mypy src/

# Tests
pytest

# Docs build (strict mode — catches broken links)
python3 scripts/check_docs_nav.py
python3 -m mkdocs build --strict -q
```

Run them in this order. Fix linter and type errors before running tests, and run `check_docs_nav.py` before the docs build to get clearer error messages.

---

## Submit a pull request

1. Create a branch from `main`:

   ```bash
   git checkout -b feature/my-change
   ```

2. Make your changes. Add or update tests as appropriate.

3. Run the full check suite (see above). All five gates must pass.

4. Commit with a descriptive message (present-tense imperative, under 72 characters):

   ```
   Add support for DeclaredUserType in patch_user_attributes
   Fix token expiry buffer calculation
   ```

5. Push and open a pull request against `main`. Describe what changed and why.

All PRs require at least one passing CI run before merging. The CI runs the same five commands listed above.

---

## Update docs when source code changes

When you change `src/quilt_hp/`, update the corresponding reference documentation in the same pull request:

| Source change | Documentation to update |
|---|---|
| New or changed `QuiltClient` method | `docs/reference/client.md` |
| New or changed model field | `docs/reference/models.md` |
| New or changed token protocol | `docs/reference/token-management.md` |
| New or changed service class | `docs/reference/models.md` |
| Changed exception type or message | `docs/reference/client.md` |
| New or changed HDS entity semantic | `docs/reference/hds-entities.md` |
| Changed wrapped RPC coverage | `docs/reference/grpc-services-matrix.md` |

Stale documentation is a maintenance hazard. Reviewers will check that docs reflect the code.

---

## Update docs when proto definitions change

When you change a `.proto` file in `proto/cleaned/`:

1. Edit the proto file.

2. Regenerate the stubs:

   ```bash
   ./scripts/regen_protos.sh
   ```

   For detailed steps and troubleshooting, see [Regenerate protobuf stubs](regenerate-protos.md).

3. Update the service wrapper in `src/quilt_hp/services/` for any new or changed RPC.

4. Update `QuiltClient` in `src/quilt_hp/client.py` if the change is exposed publicly.

5. Update documentation:

   | Proto change | Documentation to update |
   |---|---|
   | New RPC method | `docs/reference/grpc-services-matrix.md` |
   | Removed RPC method | `docs/reference/grpc-services-matrix.md` + `docs/reference/client.md` |
   | New proto file / service | `docs/explanation/grpc-and-protobuf.md`, `docs/reference/grpc-services-matrix.md` |
   | Changed message fields | `docs/reference/hds-entities.md` or `docs/reference/models.md` |

6. Run all checks:

   ```bash
   ruff check src/
   mypy src/
   pytest
   python3 scripts/check_docs_nav.py
   python3 -m mkdocs build --strict -q
   ```

7. Commit proto changes, regenerated stubs, source changes, and doc updates together in one pull request.
