---
description: dpm-xl compared with pydpm-xl and dpmcore on parse speed, coverage of the EBA rules, footprint, error messages and capabilities.
---

# Benchmarks

Three Python packages parse DPM-XL: dpm-xl, **pydpm-xl** and **dpmcore**.
They overlap only partly. pydpm-xl and dpmcore are DPM toolkits built
around the DPM database: they check rule syntax with an ANTLR grammar and
check rule *semantics* against a DPM release (do the tables, rows and columns
exist, do the types fit). dpmcore also migrates DPM databases, serves them
over a REST API and generates scripts for an external rule engine. dpm-xl
does not read the DPM database; it parses rules and **evaluates** them
against report data, and explains every failure. This page compares what
they share and lists what each does alone, to help you choose, or combine
them.

## Capabilities

| | dpm-xl | pydpm-xl | dpmcore |
| --- | --- | --- | --- |
| **Parsing** | | | |
| Syntax check of every EBA 3.4–4.4 rule and precondition | yes | yes | yes |
| DPM-XL constructs beyond the EBA rules (12 tested below) | 12 | 2 | 11 |
| Syntax errors | Plain words, character position, `pointer()` marking the text | ANTLR parser messages | ANTLR parser messages, prefixed "Unexpected error" |
| Expression tree | Frozen nodes with source spans, `walk`, static `references` and `tables` | ANTLR tree, AST | ANTLR tree, AST |
| Tokenizer and TextMate grammar for editors | yes | no | no |
| **Evaluation** | | | |
| Evaluate rules against report data | yes | no | no; generates "engine-ready" scripts for another engine |
| EBA interval arithmetic, null logic, key joins | yes | no | no |
| Explanations of failing records | yes (`explain`) | no | no |
| Columnar evaluator for millions of open-table rows | yes (`columnar` extra, polars) | no | no |
| **CLI** | | | |
| Syntax check | `dpm-xl check` (text and JSON) | `pydpm syntax` | none |
| Evaluate rules on a data file | `dpm-xl eval` (text and JSON) | no | no |
| **Footprint** | | | |
| Runtime dependencies | none | 8, including pandas, SQLAlchemy and database drivers | antlr4 and SQLAlchemy; extras for pandas, Django, FastAPI and more |
| **Outside dpm-xl's scope** | | | |
| Semantic validation against a DPM release (tables, cells and types exist) | no | yes (`pydpm semantic`) | yes |
| Operation scopes and table metadata from the DPM database | no | yes | yes |
| Migrate the EBA Access database to SQLite or another SQL database | no | yes (`pydpm migrate-access`) | yes (`dpmcore migrate`) |
| REST API, dependency graphs, layout exports | no | no | yes |
| Read xBRL-CSV and XBRL-XML report files | no; use [dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/) ([end-to-end guide](../guides/end-to-end.md)) | no | no |

If you need to know whether a rule is valid *for a given DPM release*,
pydpm-xl or dpmcore does that and dpm-xl does not. If you need to know
whether a *report* satisfies the rules, and why not, dpm-xl does that and
the other two do not. The two uses combine: check rules semantically when you
load a release, evaluate them with dpm-xl when a report arrives.

## Results

The corpus is every distinct rule and precondition expression of EBA DPM
releases 3.4 to 4.4: 14,174 expressions. All three packages reject the same
two, which contain typos in the EBA source (`trueendif` and `ornot`).

--8<-- "benchmarks/results.md"

## Method and reproduction

Each package was installed from PyPI (dpm-xl from this repository) into its
own virtual environment, dpmcore with its `cli` and `migration` extras (its
core alone needs antlr4 and SQLAlchemy). Each measurement is a separate process that runs
the package's public syntax-check API, so the times include interpreter
start-up and imports: one warm-up run, then the best wall-clock time of three
runs, with the peak resident memory of those runs. dpm-xl's syntax check is
`parse_program`, what `dpm-xl check` runs.

The scripts, the input files and the exact commands are in
[`benchmarks/`](https://github.com/luukhopman/dpm-xl/tree/main/benchmarks);
its README explains how to build the corpus from the EBA DPM databases (it is
derived from EBA data, so it is not in the repository), install each package
and regenerate this page. Absolute times depend on the machine and its load;
the ratios between the packages are the more stable result.

Semantic validation, which pydpm-xl and dpmcore offer and dpm-xl does not,
was not timed: it needs a migrated DPM database and has no dpm-xl
counterpart. Rule evaluation was not compared for the same reason in the
other direction.
