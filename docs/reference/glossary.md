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

report package
:   A ZIP that holds a report in the layout of
    [Report Packages 1.0][report-packages]: one top-level folder with
    `META-INF/reportPackage.json` and a `reports` folder.

taxonomy package
:   A ZIP of taxonomy files with a catalogue that maps their URLs to the
    files inside, under [Taxonomy Packages 1.0][taxonomy-packages]. With it,
    a report's metadata resolves offline.

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

module
:   A set of templates reported together, such as COREP large exposures
    (`COREP_LE`). A report is for one module, named by its entry point.

module file
:   A JSON document that describes one module of a DPM release: its tables,
    cells, datapoints and validation rules. dpm-xl reads it in the
    `dpm-module/1` format; dpm-synth reads the same fields as its template,
    in the `dpm-synth-template/1` format. An exporter of your own writes it
    from the release; see [the toolkit](../toolkit.md).

template
:   A reporting form with a code such as `C_27.00`, made of one or more
    tables. In dpm-synth, a *template* is also the module file it
    generates reports from.

data point
datapoint
:   A cell of a template, with a code such as `dp5488013`. It fixes the
    concept and the dimensions of the fact reported in it. Written
    `datapoint` in xBRL-CSV files and in the dpm-xbrl API.

open table
:   A table whose rows the reporter adds, such as one row per counterparty.
    Each row is identified by its key column values.

key column
:   A column of an open table whose values identify the row, such as a
    counterparty code. In DPM-XL, the dimension behind it is an open key.

filing indicator
:   A code in a report, such as `C_27.00`, that says whether a template is
    reported (`true`) or not (`false`).

DPM-XL
:   The DPM expression language, in which the EBA writes its validation
    rules, such as `{tC_01.00, c0010}: {r0010} = {r0020} + {r0030}`.

## Rules

filing rules
:   The EBA's technical rules for how a report file is written: encoding,
    naming, one entity and reference date, filing indicators, decimals,
    units. dpm-xbrl checks them; see
    [standards and conformance](standards.md).

validation rules
:   The EBA's rules on the values of a report, written in DPM-XL, such as a
    total equal to the sum of its parts. dpm-xl evaluates them.

finding
:   One filing rule a report breaks, as dpm-xbrl reports it: the rule
    number, tag, severity, count and locations.

severity
:   `error` for a rule the EBA states with MUST (the report is rejected),
    `warning` for one it states with SHOULD.
