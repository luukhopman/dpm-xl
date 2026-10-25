---
description: Set up a development environment, run the checks, write docs and send a change.
---

# Contributing

Issues and pull requests are welcome at
[github.com/luukhopman/dpm-xl](https://github.com/luukhopman/dpm-xl).
[`AGENTS.md`](https://github.com/luukhopman/dpm-xl/blob/main/AGENTS.md) in
the repository has the same conventions in a form for coding agents.

## Set up

dpm-xl uses [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/luukhopman/dpm-xl
cd dpm-xl
uv sync
```

`uv sync` installs the package with the test, lint and docs tools.

## Checks

Every change must keep these green:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run python scripts/build_docs.py
```

The docs build is strict: a broken link, an unresolved API reference or a
missing page fails it. `uv run zensical serve` previews the site while you
write.

## Conventions

- **Tests for every behaviour.** `tests/test_columnar.py` checks that both
  evaluators agree case by case; add a case there when you touch either.
  `tests/test_grammar_coverage.py` has an example for every alternative of
  the DPM-XL grammar, and `tests/data/eba_expressions.txt` samples about 300
  EBA rule expressions; every line must parse.
- **No new runtime dependencies.** The package has none; polars is the only
  optional one.
- **Google-style docstrings** for every public name, with an `Examples:`
  section where it helps. They feed the API reference and are run as
  doctests.
- **Keep `__all__` and the docs in step.** A new public name goes in its
  module's `__all__`, gets a docstring, and appears in the guide or concept
  page it belongs to.
- **Docs examples run.** Every `python` and `console` block in `docs/` is
  executed by `tests/test_docs.py`, and a `text` block right after a
  `python` block must match its output exactly. Every `dpm-xl` block must
  parse, and every row of an `| Expression | Result |` table is evaluated
  against `examples/language_report.py`; see that file for the
  conventions.
- **Language reference.** A new keyword, function or other name in
  `dpmxl.grammar` needs an entry and an index row in
  `docs/reference/language.md`, and an example that uses it; the tests
  fail otherwise.
- **Grammar changes.** After changing `dpmxl.grammar`, regenerate
  `editors/dpm-xl.tmLanguage.json`:

  ```bash
  uv run python -c "import json; from dpmxl.grammar import textmate_grammar; print(json.dumps(textmate_grammar(), indent=2))" > editors/dpm-xl.tmLanguage.json
  ```

- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org)
  (`fix(evaluator): …`, `docs: …`), in the imperative, under 72 characters.
- **Changelog.** Add user-visible changes to `CHANGELOG.md` under the next
  version, one short bullet per change.

## Releases

1. Update the version in `pyproject.toml` (`uv version X.Y.Z`) and the
   changelog heading, and commit as `build: release X.Y.Z`.
2. Tag `vX.Y.Z` and publish a GitHub release. The `Publish` workflow tests,
   builds and uploads to PyPI through trusted publishing.
3. The docs site deploys from `main` on every push.
