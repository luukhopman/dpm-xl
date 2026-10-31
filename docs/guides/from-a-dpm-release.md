---
description: Get a module file for a real EBA module, such as COREP_OF, from the EBA's DPM 2.0 database in a few commands - get the database as SQLite, list its modules, export one, check it and generate a test report.
icon: lucide/database
---

# Start from an EBA DPM release

A real module has thousands of cells and rules, so its
[module file](../reference/module-file.md) is exported from the EBA's DPM
release rather than written by hand. The EBA publishes each DPM 2.0 release
as a database (a Microsoft Access file) on its
[DPM data dictionary page](https://www.eba.europa.eu/risk-and-data-analysis/reporting-frameworks/dpm-data-dictionary).
`dpm-xl export-module` reads that database and writes one module of one
release as a module file, which dpm-xl and dpm-synth both read.

## 1. Install dpm-xl

```bash
pip install dpm-xl
```

The export uses only the standard library. Steps 6 and 7 also need
`pip install "dpm-xl[xbrl]" dpm-synth`.

## 2. Get the database as SQLite

`dpm-xl` reads the database as a SQLite file with the EBA's table and
column names. Choose one of these ways to get one.

**Convert the EBA's Access file** (any release, as soon as the EBA
publishes it). Install [mdbtools](https://github.com/mdbtools/mdbtools)
(`sudo apt install mdbtools`, or `brew install mdbtools`) and the `sqlite3`
command, download and unzip the release, then convert it; for 4.4 this takes
under half a minute and makes a file of about 350 MB:

```bash
unzip "DPM2 Database_v 4_4.zip"
DB="DPM2 Database_v 4_4_20261006.accdb"
mdb-schema "$DB" sqlite | sqlite3 dpm-4.4.sqlite
{
  echo "BEGIN;"
  mdb-tables -1 "$DB" | while read -r table; do
    mdb-export -I sqlite "$DB" "$table"
  done
  echo "COMMIT;"
} | sqlite3 dpm-4.4.sqlite
```

**Download a converted one** from [dpm-toolkit](https://github.com/JimLundin/dpm-toolkit),
which publishes a SQLite file per EBA release, usually some weeks after
the EBA. List them, then download one (it is written to standard output):

```bash
pip install dpm-toolkit
dpm-toolkit versions --group release
dpm-toolkit download 4.3-errata-1 --variant converted > dpm-4.3.zip
unzip dpm-4.3.zip
```

**Use the database of the dpm2 package**, which bundles the latest release
it was built for; the first call unpacks it (about 300 MB) and prints where:

```bash
pip install dpm2
python -c "import dpm2; print(dpm2.ensure_local_db())"
```

**Or skip the conversion**: give the `.accdb` file itself to the commands
below. They then need `mdb-export` (from mdbtools) on `PATH`, and read the
tables they need into memory each time, which takes about ten seconds.

One database holds every release up to its own, so the 4.4 database can
export 4.3 too.

## 3. List the releases and modules

`dpm-xl list-modules` prints the releases of the database and the modules
of the latest one, or of `--release`. On the
[small made-up database](https://github.com/luukhopman/dpm-xl/blob/main/examples/dpm-demo.sqlite)
that the examples here use:

```console
$ dpm-xl list-modules examples/dpm-demo.sqlite
releases: 1.0, 2.0, 2.0.1
modules of release 2.0.1: 3
  DEMO   2.0.0    Demo module
  DOCS   1.0.0    Documents
  OTHER  1.0.0    Other module
```

On the EBA's 4.4 database:

```bash
dpm-xl list-modules dpm-4.4.sqlite --release 4.3
```

```text
releases: 3.4, 3.5, 4.0, 4.1, 4.2, 4.2.1, 4.2.1.1, 4.2.1.2, 4.3, 4.3.0.1, 4.4
modules of release 4.3: 57
  AE                      1.4.0    Asset Encumbrance
  AML_RA                  1.0.0    Risk assessment methodologies
  …
  COREP_OF                4.1.0    Own Funds - COREP
  …
```

## 4. Export a module

```bash
dpm-xl export-module dpm-4.4.sqlite COREP_OF --release 4.3 -o corep_of.json
```

```text
note: COREP_OF: left out 32 rules whose scope spans several modules: v0655_m, v0656_m, …, v6259_m
note: COREP_OF: rule v7551_m: corrected 'trueendif' to 'true endif' (no space before endif)
wrote corep_of.json: module COREP_OF, release 4.3: 81 tables, 21339 cells, 1418 rules
```

The notes name what the export corrected or left out of the EBA's data;
[below](#eba-data-the-export-corrects-or-leaves-out) explains each kind.
Without `-o`, the module file is written to standard output.

## 5. Check the module file

`dpm-xl check` checks every active rule against the module's tables: that
it parses, that its functions exist and that the cells it selects do. It
exits with status 1 when a rule has an error, and with `--strict` also on
a warning:

```bash
dpm-xl check corep_of.json
```

```text
2410/2410 expressions parsed; 213 inactive rules skipped
```

The count is of expressions: a rule's precondition is checked as an
expression of its own, so 1,205 active rules make 2,410 expressions.

## 6. Generate a test report

[dpm-synth] generates a report that satisfies the module's rules, as far
as it can, from the same module file:

```bash
dpm-synth generate corep_of.json -o report.zip --seed 7
```

dpm-synth prints:

```text
rules: 1418, passed: 1146, failed: 5, not applicable: 54, skipped: 213
rounds: 14 (failing rules per round: 69, 32, 22, 14, 14, 14, 14, 14, 14, 14, 7, 11, 10, 10)
still failing: e4891_n (warning), v4810_m (warning), v6050_m (warning), v6052_m (warning), v6290_m
wrote report.zip (25486 facts)
```

[Limits of the loop](https://luukhopman.github.io/dpm-synth/concepts/limits/)
explains the rules that stay failing.

## 7. Check the report

`dpm-xl check-report` reads the report with [dpm-xbrl], checks its filing
rules and evaluates the module's validation rules on it:

```bash
dpm-xl check-report corep_of.json report.zip
```

```text
report: report.zip (xbrl-csv); module COREP_OF, release 4.3
warning: reports/report.json: 1 extended metadata document could not be resolved offline (http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_of.json); tables without resolved metadata use the EBA datapoint/factValue convention
filing rules broken: 0 errors, 1 warning
  - [warning] file-naming The file name does not follow ReportSubject_Country_FrameworkCodeModuleVersion_Module_ReferenceDate_CreationTimestamp, the structure for reports sent to the EBA.
e4891_n: failed (warning)
…
v6290_m: failed
  records: 0 passed, 1 failed, 0 null
  - scalar: 208,290,245 should equal 807,250,548 (37,194,687 + 76,800,000 + 609,992,861 + 4,377,000 + max(541,000, 78,886,000)): difference 598,960,303, at least 598,960,300 given the reported precision
1418 rules: 213 skipped, 1146 passed, 5 failed, 54 not_applicable (1413 not listed; --all lists every rule)
```

The counts are dpm-synth's, and only the five failing rules are listed.
The first warning means the EBA taxonomy was not available offline; the
report is still read, and
[`--taxonomy-package`](../reference/cli.md#dpm-xl-check-report) resolves
it. The file-naming warning is a filing rule: a generated report is not
named as one sent to the EBA.

## Which release?

The release you export selects two things: the version of the module in
force in it, and its rules in that release. The module version's tables,
cells and enumerations are exported as the EBA published them with that
version, which is what its taxonomy (and so a report of it) uses, even when
a later release changes a category the version uses. COREP_OF 4.1.0, for
example, came with release 4.2, so its entry point is
`…/fws/corep/4.2/mod/corep_of.json` in releases 4.2 to 4.4.

The basis is the release that introduced the module version: the
subcategory versions its headers and variables name are kept, and each
item takes its category bindings valid in that release. An item that moves
to another category in that release has both qnames, as the taxonomy
mostly lists both, the binding that starts later first.

Whether a rule is active is not tied to a release: the EBA deactivates rules
in the database itself, in releases such as 4.3.0.1. Export from the newest
database to get the current state. The June 2026 database of 4.3 has 27
COREP_OF rules active that the September deactivation release switched
off; exported from the 4.4 database, COREP_OF 4.3 has 1,205 active rules
and 213 inactive.

## What the export writes

| Field | From the DPM database |
| --- | --- |
| `release`, `module` | The release code and the module code. |
| `entry_point` | Built from the framework code, the release that introduced the module version and the module code, as the EBA names its entry points: `http://www.eba.europa.eu/eu/fr/xbrl/crr/fws/corep/4.2/mod/corep_of.json`. This matches the entry points of every module in the EBA's 4.2, 4.3 and 4.4 taxonomy packages. |
| `reference_date` | The module version's first reference date. |
| `decimals` | `m` 0, `p` 4, `i` 0, `r` 2, within EBA filing rule 2.18; change them if your reports use others. |
| `filing_indicators` | The module's parameters, one per template. |
| `tables` | The module version's concrete tables. An abstract table is not exported; its code is the `filing_indicator` of the tables it groups, such as `C_07.00` for `C_07.00.a`. |
| `open_keys` | The key headers of an open table: the property code, and the items of an enumerated property (restricted by the header's subcategory, if it has one) or the data type of a typed one. |
| `cells` | Every cell that is neither excluded nor void: its row, column and sheet codes (`*` on an open axis), `dp` and the variable ID as the datapoint, the data type of the variable's property (its DPM code, such as `m` or `es`), and the items of an enumerated (`e`) cell: those of the subcategory that its row, column or sheet header sets for the property, else of the variable, else every active item of the property's category. |
| `rules` | The rules whose scope is this module alone: expression, precondition, severity, `active: false` for a rule the EBA deactivated, and as `modules` every module with such a scope for the rule. |

A monetary cell whose variable's context sets property `qAEA` to
`qCA:qx2000` (the currency of denomination) has `unit: true`: it is
reported in its own currency, in the table's `unit` column. In release 4.3
these are 10,183 cells, and they match the datapoints whose unit is `$unit`
in the EBA's 4.2 to 4.4 taxonomy packages, with none differing.

## EBA data the export corrects or leaves out

The EBA's database has a few known errors and inconsistencies. The export
handles each one the same way every time, and reports it in a note
(a warning of the `dpmxl.dpm` logger in Python):

- **Typos in two rule expressions** stop them from parsing: `v7551_m` has
  `trueendif` and `v904909_m` has `ornot`. The export inserts the missing
  space ([`KNOWN_ERRORS`][dpmxl.dpm.KNOWN_ERRORS]).
- **Rules whose scope spans several modules**, such as `v0655_m` on COREP_OF
  and COREP_LE, select tables of both, so one module's report can never
  satisfy them. The export leaves them out.
- **Items whose binding ended** before the release while a subcategory
  still lists them keep their last code, as in the EBA's taxonomy.
- **Items outside the property's category**, which a subcategory of
  another category lists (such as `_PR` items for a RESOL property of
  `_NA` in releases 3.4 to 4.1), have no qname there and are left out.
- **Modules without tables**, such as the Pillar 3 document modules, cannot
  be exported; the command says so and exits with status 3.

## How accurate is it

For every module of releases 4.3 and 4.4 (each exported from the database
of its release), the items of every enumerated cell and open key were
compared with the allowed values the EBA lists in the module's taxonomy
package (`AllowedValue` in each table's xBRL-CSV metadata):

| Release | Enumerated cells equal | Enumerated keys equal |
| --- | --- | --- |
| 4.3 | 1,173 of 1,176 | 214 of 214 |
| 4.4 | 1,187 of 1,190 | 234 of 234 |

With the taxonomy packages (below), all of them are equal.

The three cells that differ are on boundaries where the database and the
taxonomy disagree: an item whose category binding ends in the module's
release, which the taxonomy no longer lists, and items that move to another
category, which the taxonomy lists under both codes although the property's
category is only the new one. DORA (with its own taxonomy package) and
FINREP9DP 1.1.0 (release 4.2.1) were not compared.

## Items from the taxonomy

For items exactly as reports are validated against them, give the export
the EBA's taxonomy packages that hold the module version's entry point
(the release that introduced it, and for older versions its packages too):

```bash
dpm-xl export-module dpm-4.4.sqlite COREP_OF --release 4.3 -o corep_of.json \
  --taxonomy-package EBA_XBRL_4.2_Reporting_Frameworks_4.2.0.0.zip \
  --taxonomy-package EBA_XBRL_4.3_Reporting_Frameworks_4.3.0.0.zip
```

Each enumerated cell and key then takes its items, in the taxonomy's order,
from the allowed values of its table's xBRL-CSV metadata, and from the
database where the taxonomy lists none. A module whose entry point no
package has is exported from the database alone, with a note. In Python,
pass `taxonomy_packages` to [`export_module`][dpmxl.dpm.export_module].

## In Python

[`open_release`][dpmxl.dpm.open_release] opens the database and
[`export_module`][dpmxl.dpm.export_module] returns the module file as a
dictionary:

```python
from dpmxl.dpm import export_module, open_release
from dpmxl.module import load_module

with open_release("examples/dpm-demo.sqlite") as db:
    print([module.code for module in db.modules()])
    document = export_module(db, "DEMO", "2.0")
module = load_module(document)
print(module.release, [table.code for table in module.tables])
print(document["tables"][1]["open_keys"][0])
print([(rule.code, rule.active) for rule in module.rules])
```

```text
['DEMO', 'DOCS', 'OTHER']
2.0 ['T_01.00.a', 'T_02.00']
{'code': 'qKEY', 'column': 'qKEY', 'items': ['eba_CA:x2', 'eba_CA:x1', 'eba_CA:x4']}
[('v1', True), ('v6', False), ('v7551_m', True)]
```

Write it with `json.dump(document, file)`. The notes go to the `dpmxl.dpm`
logger; Python prints its warnings to standard error unless you configure
logging.
