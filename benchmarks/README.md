# Benchmarks

Scripts behind the [Benchmarks](https://luukhopman.github.io/dpm-xl/project/benchmarks/)
page: dpm-xl against the other Python packages that parse DPM-XL, pydpm-xl
and dpmcore. They are not part of the package and the test suite does not run
them.

| File | Purpose |
| --- | --- |
| `run.py` | Runs every measurement and writes `results.md` (included by the docs page) and `results.json`. |
| `worker.py` | Runs inside each tool's environment: import, corpus syntax check, messages for given expressions. |
| `build_corpus.py` | Builds the EBA expression corpus from DPM databases. |
| `inputs/constructs.txt` | DPM-XL constructs beyond the EBA 3.4–4.4 rules. |
| `inputs/malformed.txt` | Malformed expressions for comparing syntax error messages. |

## 1. Build the corpus

The corpus is every distinct rule and precondition expression of EBA DPM
releases, one per line. It is derived from EBA data, so it is not committed.

1. Download the DPM 2.0 database of each release from the EBA website (a
   Microsoft Access `.accdb` file).
2. Migrate each to SQLite, for example with dpmcore (installed in step 2):
   `envs/dpmcore/bin/dpmcore migrate --source dpm-4.2.1.accdb --database sqlite:///dpm-4.2.1.db`.
3. Build the corpus from all of them:

   ```bash
   python benchmarks/build_corpus.py corpus.txt dpm-3.4.db dpm-4.0.db dpm-4.2.1.db
   ```

The published numbers use 14,174 expressions from releases 3.4 to 4.4; the
4.2.1 database alone gives 13,158 of them.

## 2. Install each tool in its own environment

Each tool gets a separate virtual environment, so that none shares
dependencies with another and the footprint can be measured:

```bash
uv venv -p 3.12 envs/dpm-xl   && uv pip install -p envs/dpm-xl/bin/python .
uv venv -p 3.12 envs/pydpm-xl && uv pip install -p envs/pydpm-xl/bin/python pydpm-xl==0.3.12
uv venv -p 3.12 envs/dpmcore  && uv pip install -p envs/dpmcore/bin/python "dpmcore[cli,migration]==0.2.1"
```

Install dpm-xl from the checkout (`.`) to measure the current code.
dpmcore gets the `cli` and `migration` extras, which step 1 uses; they add
pandas, numpy, click and rich to its footprint. `envs/`
is ignored by git.

## 3. Run

```bash
python benchmarks/run.py --corpus corpus.txt \
    --env dpm-xl=envs/dpm-xl --env pydpm-xl=envs/pydpm-xl --env dpmcore=envs/dpmcore
```

It takes about eight minutes and needs Linux (it reads `/proc/cpuinfo` and
measures peak memory with `os.wait4`). Run it on an otherwise idle machine:
other load slows every tool, though the ratios between them hold up better
than the absolute times.

Method: every measurement is a separate process,
`envs/<tool>/bin/python -I benchmarks/worker.py <tool> <task>`, so it
includes interpreter start-up and imports. Each runs once to warm the
file-system cache, then three more times; the table shows the best wall-clock
time and the highest peak RSS of those three. The syntax check uses each
tool's public API, the same one its CLI uses:

| Tool | Call |
| --- | --- |
| dpm-xl | `dpmxl.parse_program(expression)`, as `dpm-xl check` |
| pydpm-xl | `py_dpm.api.SyntaxAPI().validate_expression(expression)` |
| dpmcore | `dpmcore.services.syntax.SyntaxService().validate(expression)` |

"Installed environment" counts the distributions in the environment (pip,
setuptools and wheel excluded) and the size of its `site-packages`.

Commit `results.md` and `results.json` with the docs change that uses them.
