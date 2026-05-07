# Documentation standards

Use these standards to keep the docs practical for engineers integrating Quilt.

## 1) Write for implementers

- Focus on behavior, contracts, and integration guidance.
- Prefer concise explanation of what to call, when to call it, and expected
  outcomes.
- Avoid repetitive meta-labeling in user-facing pages.

## 2) Keep API references accurate

- The signature reference page is generated from source:
  `docs/python-api/public-api-reference.md`.
- Regenerate it whenever public APIs change:

```bash
python scripts/generate_public_api_reference.py
```

- Narrative API pages should explain semantics, edge cases, and examples;
  generated pages provide the complete signature surface.

## 3) Diagrams

- Use in-document Mermaid for lifecycle and flow diagrams.
- Prefer `flowchart` for data/control flow and `sequenceDiagram` for protocol
  interactions.

## 4) Docs quality gates

Before opening or updating a PR with docs changes, run:

```bash
python scripts/check_docs_nav.py
mkdocs build --strict
```

- `check_docs_nav.py` ensures every docs page is represented in nav and every
  nav page exists.
- `mkdocs build --strict` catches broken links and build-time doc errors.
