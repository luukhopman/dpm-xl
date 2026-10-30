# AGENTS.md

Instructions for coding agents working on this repository. Users of the
library want https://luukhopman.github.io/dpm-xl/agents/ instead.

## What this is

dpm-xl is a dependency-free Python (3.11+) parser and evaluator for DPM-XL,
the EBA validation-rule language. It is an independent project, not
affiliated with or endorsed by the European Banking Authority.

## Layout

| Path | Content |
| --- | --- |
| `src/dpmxl/` | The package. `parser.py` (tokenizer, recursive-descent parser), `grammar.py` (vocabulary, TextMate grammar), `ast.py` (frozen node classes), `values.py` (`Number` with interval tolerance), `recordset.py` (keyed records, joins), `evaluator.py` (reference evaluator), `explain.py`, `references.py` (static analysis), `provider.py` (`DataProvider`, `MemoryProvider`), `rules.py` (rule files), `module.py` (module files), `dpm.py` (module files from an EBA DPM 2.0 database), `xbrl.py` (report bridge, optional), `columnar.py` (polars evaluator, optional), `cli.py`. |
| `tests/` | pytest suite. `test_columnar.py` checks both evaluators agree; `test_grammar_coverage.py` covers every grammar alternative; `test_docs.py` runs every docs example and docstring doctest and checks that the language reference covers `dpmxl.grammar`; `data/eba_expressions.txt` samples EBA rules and `data/eba_corpus.json.gz` holds all 14,174 EBA expressions of DPM 3.4–4.4 (source in `data/eba_corpus.md`), which `test_corpus.py` parses. |
| `docs/` | Documentation site (Zensical + mkdocstrings), configured in `zensical.toml`. |
| `scripts/build_docs.py` | Strict site build plus `llms.txt`, `llms-full.txt` and Markdown page copies. |
| `examples/` | Runnable examples and data used by the docs and tests; `language_report.py` is the report the language reference's examples run against. `dpm_demo.py` builds `dpm-demo.sqlite`, a small made-up DPM 2.0 database. |
| `benchmarks/` | Comparison scripts; not run by the tests. |
| `editors/dpm-xl.tmLanguage.json` | Generated from `dpmxl.grammar`. |

## Commands

```bash
uv sync                                    # install with test, lint and docs tools
uv run pytest                              # tests, docs examples and doctests
uv run ruff check . && uv run ruff format --check . && uv run ty check
uv run python scripts/build_docs.py        # strict docs build into site/
uv run zensical serve                      # preview the docs
```

Regenerate the editor grammar after changing `src/dpmxl/grammar.py`:

```bash
uv run python -c "import json; from dpmxl.grammar import textmate_grammar; print(json.dumps(textmate_grammar(), indent=2))" > editors/dpm-xl.tmLanguage.json
```

## Conventions

- No new runtime dependencies; polars stays optional (`columnar` extra) and
  dpm-xbrl too (`xbrl` extra); their tests skip without them. Docs tools
  belong in the `docs` dependency group.
- The `xbrl` extra needs dpm-xbrl 1.1, which is not on PyPI yet, so
  `[tool.uv] override-dependencies` lets the lock take dpm-xbrl 1.0. Once
  1.1 is published, remove the override and run `uv lock`. To work against
  a local dpm-xbrl checkout, run
  `uv pip install --no-config -e ../dpm-xbrl` and then `uv run --no-sync`.
- The `docs` group takes dpm-synth from its GitHub `main` branch through
  `[tool.uv.sources]`, for the toolkit tour, because dpm-synth 1.0.0 is not
  on PyPI yet. Once it is published, remove that source and run `uv lock`
  so dpm-synth resolves from PyPI like dpm-xbrl.
- Google-style docstrings for every public name, with `Examples:` doctests
  where they help; cross-references as `` [`Name`][dpmxl.module.Name] ``
  (the defining module), never Sphinx roles.
- Keep `__all__`, docstrings and `docs/` in step: a new public name goes in
  its module's `__all__`, gets a docstring, and appears in the relevant docs
  page. Public API = every name in a module's `__all__`.
- Tests for every behaviour. A change to evaluation semantics needs a case
  in `tests/test_columnar.py` (both evaluators must agree) or a reason why
  the columnar evaluator raises `ColumnarUnsupported` for it.
- Every `python` and `console` block in `docs/` and `README.md` is executed;
  a `text` block directly after a `python` block must equal its output. Use
  `<!-- docs: skip -->` sparingly. Real outputs only; the tests ignore the
  version in JSON and JUnit output, so samples need not change with it.
- Every row of an `| Expression | Result |` table is evaluated against
  `examples/language_report.py` and must show the actual result. A change
  to `dpmxl.grammar` needs its entry and index row in
  `docs/reference/language.md` (the tests check both directions).
- Code annotations (`# (1)!` comments with a numbered list right after
  the block) may stand between a `python` block and its `text` output;
  the docs tests check that each annotation has its list item.
- Shared link targets for the docs (such as the dpm-xbrl site and the
  specifications) are in `docs/.snippets/links.md`; the glossary tooltips,
  auto-appended to every page, in `docs/.snippets/glossary.md`, with each
  term also on `docs/reference/glossary.md`.
- Versions of the standards implemented, and how they are tested, belong
  on `docs/reference/standards.md`; other pages link there. The deviations
  from DPM-XL stay in `docs/reference/language.md#where-dpm-xl-differs`.
- The toolkit cards, the toolkit page, the glossary and
  `docs/stylesheets/toolkit.css` are the same in dpm-xl, dpm-xbrl and
  dpm-synth; `tests/test_toolkit.py` pins their hashes.
- `evaluate_rule` never raises for bad rules or data; it returns a status.
  Keep it that way.
- Statuses, record keys, field names and the CLI JSON layout
  (`schema_version`) are stable; explanation and error wording may change in
  minor releases.
- Conventional Commits (`fix(evaluator): ...`, `docs: ...`), imperative,
  subject under 72 characters, no trailing period.
- User-visible changes get one short bullet in `CHANGELOG.md`.
- British or neutral spelling; plain, precise, concise prose.
- Do not edit `.github/workflows/publish.yml` or the version without the
  maintainer.

## Release process

1. `uv version X.Y.Z`, move the changelog entries under a `## X.Y.Z - date`
   heading, commit `build: release X.Y.Z`.
2. Tag `vX.Y.Z` and publish a GitHub release; `publish.yml` tests, builds and
   uploads to PyPI through trusted publishing.
3. `docs.yml` deploys the site from `main`.
