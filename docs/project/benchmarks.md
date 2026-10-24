---
description: dpm-xl compared with pydpm-xl and dpmcore on capabilities, licence, parse speed, coverage of the EBA rules, footprint and error messages.
---

# Benchmarks

Three Python packages parse DPM-XL. pydpm-xl and dpmcore validate rules
against a DPM database; dpm-xl evaluates rules against report data and
explains failures. The table shows where they overlap and where they differ.

## Capabilities

| | dpm-xl | pydpm-xl | dpmcore |
| --- | --- | --- | --- |
| Licence | MIT | GPL-3.0-or-later | Apache-2.0 |
| Runtime dependencies | none | 8 (pandas, SQLAlchemy, database drivers) | antlr4, SQLAlchemy |
| Parses every EBA 3.4–4.4 rule | yes | yes | yes |
| Syntax errors | plain words with position | ANTLR messages | ANTLR messages |
| Evaluates rules against report data | yes | no | no |
| Explains failing records | yes | no | no |
| Columnar evaluation for millions of rows | yes | no | no |
| CLI to evaluate rules on a data file | yes | no | no |
| Tokenizer and editor grammar | yes | no | no |
| *Outside dpm-xl's scope:* | | | |
| Semantic validation against a DPM release | no | yes | yes |
| DPM database migration, REST API | no | migration | yes |
| Reads report files | via [dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/) | no | no |

Use pydpm-xl or dpmcore to check that a rule fits a DPM release; use dpm-xl
to check that a report satisfies the rules, and why not. The two combine.

## Results

The corpus holds the 14,174 distinct rule and precondition expressions of
EBA DPM releases 3.4 to 4.4. All three packages reject the same two, which
contain typos in the EBA source.

--8<-- "benchmarks/results.md"

## Method

Each package runs in its own virtual environment from PyPI (dpm-xl from this
repository), as a separate process through its public syntax-check API: one
warm-up, then the best of three runs, with peak memory. Ratios between the
packages are more stable than absolute times. Scripts and instructions are in
[`benchmarks/`](https://github.com/luukhopman/dpm-xl/tree/main/benchmarks).
