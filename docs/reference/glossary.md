---
description: The terms of EBA reporting, XBRL and the DPM used in the dpm-xl, dpm-xbrl and dpm-synth documentation, with short definitions.
icon: lucide/book-a
---

# Glossary

The terms these pages use, as the EBA and XBRL International use them. The
abbreviations and the terms marked with a dotted underline have the same
definitions as tooltips on every page. The glossary is the same on the
[dpm-xl], [dpm-xbrl] and [dpm-synth] sites.

## Organisations and frameworks

EBA
:   European Banking Authority. It publishes the reporting frameworks, the
    taxonomies, the DPM and the [filing rules][eba-filing-rules] for
    supervisory reports in the EU.

ECB
:   European Central Bank. Its supervisory reporting follows the EBA
    taxonomies and filing rules.

COREP
:   Common Reporting: the EBA framework for own funds, capital requirements,
    large exposures and related reports.

FINREP
:   Financial Reporting: the EBA framework for financial statements.

## Reports and files

XBRL
:   eXtensible Business Reporting Language, the standard of
    [XBRL International](https://www.xbrl.org) in which EBA reports are
    written. A report is a set of facts whose meaning a taxonomy defines.

XBRL-XML
:   An XBRL report as one XML instance document, under
    [XBRL 2.1][xbrl-21]. The older form of EBA reports.

xBRL-CSV
:   An XBRL report as JSON metadata plus one CSV file per table, under
    [xBRL-CSV 1.0][xbrl-csv-spec]. The form of current EBA reports.

OIM
:   Open Information Model: the model of an XBRL report independent of its
    syntax, on which [xBRL-CSV][xbrl-csv-spec] is built.

fact
:   One reported value with what gives it its meaning: its concept,
    dimensions, entity, period and unit. In an EBA xBRL-CSV table file, a
    fact is one row: a datapoint code, the value (`factValue`) and, in an
    open table, the key column values.

qname
:   A qualified name, `prefix:name`, such as `eba_GA:DE` or `iso4217:EUR`.
    The prefix stands for a namespace of the taxonomy. Reports write
    concepts, items and units as qnames.

concept
:   The XBRL element that names what a fact measures, such as
    `eba_met:mi53`; the EBA's taxonomy calls it a metric.

dimension
:   A qualifier on a fact, such as the counterparty or the currency, given
    as an explicit member (an item) or a typed value.

hypercube
:   The dimensions and members a taxonomy allows for a concept's facts,
    under [XBRL Dimensions 1.0][xdt-spec] (XDT). dpm-xbrl checks facts
    against them when given the taxonomy packages.

XDT
:   XBRL Dimensions 1.0, the specification of dimensions and hypercubes;
    section numbers are written as "XDT §3.1.1".

report package
:   A ZIP that holds a report in the layout of
    [Report Packages 1.0][report-packages]: one top-level folder with
    `META-INF/reportPackage.json` and a `reports` folder.

taxonomy
:   The XBRL definition of a framework's reports: the concepts, dimensions,
    tables and entry points that give each fact its meaning. The EBA
    generates a taxonomy from each DPM release.

taxonomy package
:   A ZIP of taxonomy files with a catalogue that maps their URLs to the
    files inside, under [Taxonomy Packages 1.0][taxonomy-packages]. The EBA
    publishes each release's taxonomy as taxonomy packages. With them, a
    report's metadata resolves offline.

metadata
:   The JSON table descriptions a report's `report.json` extends from the
    taxonomy: what each column of an xBRL-CSV table means. Without the
    taxonomy packages, dpm-xbrl reads EBA tables by their `datapoint` and
    `factValue` columns instead, the EBA convention, and facts get
    datapoint codes but no concept or unit.

entry point
:   The taxonomy file a report refers to (`report.json` extends it, an XML
    instance's `link:schemaRef` points to it). It fixes the framework, the
    module and the version.

reference date
:   The date the values of a report refer to: `refPeriod` in
    `parameters.csv`, or the instant of the XML contexts.

LEI
:   Legal Entity Identifier: a 20-character code for a legal entity, with
    two check digits (ISO 17442). Reports identify their entity by LEI or by
    a national code.

UTR
:   XBRL Units Registry: the units, such as ISO 4217 currencies and
    `xbrli:pure`, that reports may use.

## The data point model

DPM
:   Data Point Model: the EBA's dictionary of its reporting frameworks. It
    defines modules, templates, tables, data points and the validation
    rules, and the taxonomies are generated from it.

release
:   A version of the DPM and of the taxonomy generated from it, such as
    `4.3`. The EBA's DPM database holds every release up to its own, so
    the 4.4 database also describes release 4.3.

module
:   A set of templates reported together, such as COREP large exposures
    (`COREP_LE`). A report is for one module, named by its entry point.

reporting template
template
:   An EBA reporting form with a code such as `C_07.00`, made of one or
    more tables. A report says which templates it includes with its filing
    indicators. In these pages, *template* on its own means a reporting
    template.

table
:   One grid of a template, with rows, columns and sometimes sheets. A
    template of one table shares its code, such as `C_01.00`; the tables
    of a larger template add a letter, such as `C_07.00.a` and
    `C_07.00.b`. Rules select cells by table, row (`r0010`), column
    (`c0010`) and sheet. An xBRL-CSV report has one file per table, named
    by its code in lower case (`c_07.00.a.csv`). In dpm-xbrl,
    `Fact.template` holds the table code.

sheet
:   The third axis of a table, after rows and columns, with codes such as
    `s0010`. A table with sheets repeats its rows and columns on each
    sheet, such as one sheet per country.

data point
datapoint
:   A cell of a table, with a code such as `dp5488013`. It fixes the
    concept and the dimensions of the fact reported in it. Written
    `datapoint` in xBRL-CSV files and in the dpm-xbrl API.

item
:   A member of a DPM domain, such as a country or an exposure class,
    written as a qname such as `eba_GA:DE`. Enumerated cells and keys take
    items; DPM-XL writes one in square brackets: `[eba_GA:DE]`.

open table
:   A table whose rows the reporter adds, such as one row per
    counterparty. Each row is identified by its key column values. In some
    open tables it is the sheets that the reporter adds, one per key value,
    and the rows stay fixed. A table with a fixed set of cells is closed.

key column
:   A column of an open table whose values identify the row, such as a
    counterparty code. In DPM-XL, the dimension behind it is an open key.

filing indicator
:   A code in a report, such as `C_27.00`, that says whether a template is
    reported (`true`) or not (`false`).

module file
template file
:   A JSON document that describes one module of one release: its tables,
    cells, datapoints and validation rules, in the `dpm-module/1` format.
    `dpm-xl export-module` writes it from an EBA DPM release; dpm-xl checks
    reports against it, and dpm-synth generates reports from it. dpm-synth
    calls its input the *template file*: a module file, or the same fields
    in its `dpm-synth-template/1` format. See [the toolkit](../toolkit.md).

DPM-XL
:   The DPM expression language, in which the EBA writes its validation
    rules, such as `with {tC_01.00, c0010}: {r0010} = {r0020} + {r0030}`.

## Rules

validation rules
:   The EBA's rules on the values of a report, written in DPM-XL, such as a
    total equal to the sum of its parts. dpm-xl evaluates them.

rule
expression
:   A validation rule is an expression in DPM-XL, with an optional
    precondition and a severity, under a code such as `v0001`.
    `dpm-xl check` counts a rule's expression and its precondition as two
    expressions.

precondition
:   A DPM-XL condition attached to a validation rule, usually the filing
    indicator of the template the rule checks, such as `{v_C_07.00}`. The
    rule is evaluated only when the precondition holds; otherwise it is
    `not_applicable`.

rule status
:   The outcome of evaluating one validation rule: `passed`; `failed`;
    `not_applicable` (the precondition is false, or there is nothing to
    check); `error` (the rule cannot be evaluated, such as `+` on a text
    cell); `unsupported` (it needs something the evaluation does not have,
    such as last period's report for `time_shift`); or `skipped` (the rule
    is inactive or for another module). The status `error` is not the
    severity `error`.

filing rules
:   The EBA's technical rules for how a report file is written: encoding,
    naming, one entity and reference date, filing indicators, decimals,
    units. dpm-xbrl checks them; see
    [standards and conformance](standards.md).

finding
:   One problem with a report file. Mostly a filing rule it breaks, as
    dpm-xbrl reports it: its severity, rule number (or id), title, tag,
    spec code, message, count and locations. The tag is the EBA's short
    code for the condition, such as `nilUsed`. `dpm-xl check-report` adds
    fact findings for facts it cannot place in the module or read as their
    data type, such as `unplacedFact`, `invalidValue` and `duplicateFact`.

severity
:   How serious a broken rule is: `error` or `warning`.

    - A validation rule's severity comes from the DPM: `error` for a
      blocking rule, `warning` for one that only flags a possible problem.
    - A filing rule's severity follows the EBA's wording: `error` for a
      rule stated with MUST (the report is rejected), `warning` for one
      stated with SHOULD.

    `--fail-on` sets the least severity that fails a run; the default is
    `error`.

spec code
:   The error code an XBRL International specification gives a condition,
    such as `xbrlce:unknownColumn`. dpm-xbrl gives it on a finding as
    `spec_code`, next to the EBA rule number, for comparison with other
    XBRL tools.

profile
:   A supervisor's variant of the EBA filing rules, chosen with
    `dpm-xbrl inspect --profile`. `eba`, the default, keeps every rule;
    `dnb` leaves out the rules De Nederlandsche Bank does not apply.

exit status
:   The number a command returns, the same in the three tools: 0 done, 1 a
    rule or finding at or above `--fail-on` failed (for `dpm-xl check`,
    an expression has an error), 2 a usage error, 3 unreadable or invalid
    input, or output that cannot be written.
