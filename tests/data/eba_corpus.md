# EBA expression corpus

`eba_corpus.json.gz` maps each of the 14,174 distinct DPM-XL rule and
precondition expressions of the EBA DPM 2.0 releases 3.4 to 4.4 to the code
of one rule that uses it, such as `v0001_m`. `tests/test_corpus.py` parses
every one.

Source: European Banking Authority, DPM 2.0 data dictionary, releases 3.4 to
4.4 (the `Expression` column of the `OperationVersion` table), published at
https://www.eba.europa.eu/risk-and-data-analysis/reporting-frameworks/dpm-data-dictionary.
Reused with acknowledgement of the source, as the EBA's legal notice
permits; the expressions are unchanged, except that line breaks inside an
expression became spaces. dpm-xl is not affiliated with or endorsed by the
EBA. `benchmarks/build_corpus.py` rebuilds the expressions from the
databases.
