---
description: How to report a vulnerability, and what dpm-xl does and does not protect against when it parses and evaluates rules.
---

# Security

## Reporting a vulnerability

Report vulnerabilities privately through
[GitHub security advisories](https://github.com/luukhopman/dpm-xl/security/advisories/new),
not in a public issue.

## Threat model

dpm-xl's evaluator reads no files, opens no network connections and never
executes rule text as Python. `dpmxl.dpm` reads a DPM database (SQLite,
Access, or the EBA's ZIP of it) and taxonomy package ZIPs, and runs
`mdb-export` from `PATH` without a shell; treat databases and packages from
untrusted sources accordingly. What dpm-xl does with untrusted input:

| Input | Treatment |
| --- | --- |
| Expression text | Parsed by a hand-written recursive-descent parser. Nesting deeper than 50 levels and numbers outside the decimal128 range are syntax errors, so a hostile expression cannot exhaust the stack. |
| Report data | Values are typed data (`Number`, `str`, dates, items, sets); nothing is evaluated. Joins that would produce more than 2,000,000 records are an error instead of a memory spike. |
| `decimals` | `Number.of` rejects decimals beyond the decimal128 range, which would otherwise make tolerances overflow. |
| CLI input files | Read as JSON or text; malformed input is reported with exit status 3, without a traceback. |
| DPM database ZIP | The one `.accdb`/`.mdb` member is unpacked to a temporary file and deleted; members larger than 2 GiB or compressed more than 100:1 (from 1 MiB), encrypted or Deflate64 members are input errors. |

What it does not protect against:

- **Regular expressions.** `match(s, pattern)` runs the rule's pattern with
  Python's `re` module. A pattern written to backtrack catastrophically can
  take very long on a long text. Treat rule text as code from a trusted
  source, or evaluate rules from untrusted sources with a time limit (for
  example in a separate process).
- **Rule cost.** Rules over very large selections take time and memory in
  proportion to the data. Set limits in your application when users can
  submit rules.
- **Providers.** Your provider runs inside the evaluation; it must protect
  its own data source (SQL parameters, access control).

For untrusted report *files*, see the security model of
[dpm-xbrl](https://luukhopman.github.io/dpm-xbrl/), which reads them.
