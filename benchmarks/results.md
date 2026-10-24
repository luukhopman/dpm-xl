Measured on 2026-10-24 on AMD Ryzen 7 4700U with Radeon Graphics, 8 cores, Linux 7.0.0-38-generic; Python 3.12.3. Best of 3 warm runs; peak RSS over those runs.

#### Speed and footprint

| | dpm-xl 1.0.0 | pydpm-xl 0.3.12 | dpmcore 0.2.1 |
| --- | --- | --- | --- |
| Syntax check of the corpus (whole process) | 1.61 s, 23 MB | 14.85 s, 109 MB | 15.23 s, 113 MB |
| Per expression | 113 µs | 1,047 µs | 1,075 µs |
| `import` (whole process) | 0.09 s, 18 MB | 0.75 s, 97 MB | 0.85 s, 101 MB |
| Installed environment | 1 distributions, 1 MB | 17 distributions, 142 MB | 15 distributions, 143 MB |

#### Coverage of the EBA corpus

| | dpm-xl 1.0.0 | pydpm-xl 0.3.12 | dpmcore 0.2.1 |
| --- | --- | --- | --- |
| Expressions accepted | 14,172 of 14,174 | 14,172 of 14,174 | 14,172 of 14,174 |
| Rejected | `with {default: 0, interval: true}:if sum({tC_08.01.a, r0070…`<br>`with {tV_03.01, default: null, interval: false}: if not(isn…` | `with {default: 0, interval: true}:if sum({tC_08.01.a, r0070…`<br>`with {tV_03.01, default: null, interval: false}: if not(isn…` | `with {default: 0, interval: true}:if sum({tC_08.01.a, r0070…`<br>`with {tV_03.01, default: null, interval: false}: if not(isn…` |

#### DPM-XL constructs beyond the EBA rules

| | dpm-xl 1.0.0 | pydpm-xl 0.3.12 | dpmcore 0.2.1 |
| --- | --- | --- | --- |
| rank over a partition: `with {tC_08.02}: rank({c0010} over (partition by qEEA order by qEEA desc)) > 0` | accepted | rejected | accepted |
| windowed aggregate: `with {tC_08.02}: sum({c0010} over (order by qEEA data points between unbounded preceding and current data point)) > 0` | accepted | rejected | accepted |
| statements with :=: `x := {tC_01.00, r0010, c0010}; x > 0` | accepted | rejected | rejected |
| persistent assignment <-: `{tC_01.00, r0010, c0010} <- {tC_01.00, r0020, c0010} + 1` | accepted | rejected | accepted |
| operation reference {o...}: `{oV_1234} > 0` | accepted | accepted | accepted |
| set operators and literals: `union({tC_01.00, r0010, c0010}, {tC_01.00, r0020, c0010}) = {1, 2}` | accepted | rejected | accepted |
| typed parameter {p...}: `{tC_01.00, r0010, c0010} > {pThreshold, number, default: 5}` | accepted | rejected | accepted |
| text concatenation &: `{tC_01.00, r0010, c0010} & "x" = "1x"` | accepted | accepted | accepted |
| date functions: `year({tC_01.00, r0010, c0010}) = 2026` | accepted | rejected | accepted |
| date() and date literals: `date(2026, 12, 31) = #2026-12-31#` | accepted | rejected | accepted |
| table group {g...}: `{gCOREP_OF, r0010, c0010} > 0` | accepted | accepted | accepted |
| annualise: `annualise({tC_01.00, r0010, c0010}, 2, qEBB) > 0` | accepted | rejected | accepted |

#### Syntax error messages

`{tC_01.00, r0010, c0010} >=`

- dpm-xl: expression ends where an operand is expected at position 27
- pydpm-xl: offendingSymbol: [@11,27:26='<EOF>',<-1>,1:27] msg: mismatched input '<EOF>' expecting {BOOLEAN_LITERAL, NOT, MATCH, PLUS, MINUS, MAX_AGGR, MIN_AGGR, SUM, COUNT, AVG, MEDIAN, ABS, ISNULL, EXP, LN, SQ…
- dpmcore: Unexpected error: "offendingSymbol: [@11,27:26='<EOF>',<-1>,1:27] msg: mismatched input '<EOF>' expecting {BOOLEAN_LITERAL, NOT, MATCH, PLUS, MINUS, MAX_AGGR, MIN_AGGR, SUM, COUNT, AVG, MEDIAN, RANK,…

`with {tC_01.00, c0010}: {r0010} = {r0020} +`

- dpm-xl: expression ends where an operand is expected at position 43
- pydpm-xl: offendingSymbol: [@21,43:42='<EOF>',<-1>,1:43] msg: mismatched input '<EOF>' expecting {BOOLEAN_LITERAL, NOT, MATCH, PLUS, MINUS, MAX_AGGR, MIN_AGGR, SUM, COUNT, AVG, MEDIAN, ABS, ISNULL, EXP, LN, SQ…
- dpmcore: Unexpected error: "offendingSymbol: [@21,43:42='<EOF>',<-1>,1:43] msg: mismatched input '<EOF>' expecting {BOOLEAN_LITERAL, NOT, MATCH, PLUS, MINUS, MAX_AGGR, MIN_AGGR, SUM, COUNT, AVG, MEDIAN, RANK,…

`if {tC_01.00, r0010} > 0 then true`

- dpm-xl: expected 'endif', found end of expression at position 34
- pydpm-xl: offendingSymbol: [@16,34:33='<EOF>',<-1>,1:34] msg: mismatched input '<EOF>' expecting {ENDIF, ELSE}
- dpmcore: Unexpected error: "offendingSymbol: [@16,34:33='<EOF>',<-1>,1:34] msg: mismatched input '<EOF>' expecting {ENDIF, ELSE}"

`sum({tC_01.00, r0010} group by) > 0`

- dpm-xl: expected a name, found ')' at position 30
- pydpm-xl: offendingSymbol: [@10,30:30=')',<40>,1:30] msg: missing {ROW_COMPONENT, COL_COMPONENT, SHEET_COMPONENT, PROPERTY_CODE} at ')'
- dpmcore: Unexpected error: "offendingSymbol: [@10,30:30=')',<42>,1:30] msg: missing {ESCAPED_IDENTIFIER, ROW_COMPONENT, COL_COMPONENT, SHEET_COMPONENT, PROPERTY_CODE} at ')'"

`{tC_01.00, r0010, c0010 = 5`

- dpm-xl: unterminated '{': no matching '}' at position 0
- pydpm-xl: offendingSymbol: None msg: token recognition error at: '='
- dpmcore: Unexpected error: "offendingSymbol: None msg: token recognition error at: '='"

`with {tC_01.00, c0010}: {r0010} = {r0020} +* {r0030}`

- dpm-xl: unexpected '*' where an operand is expected at position 43
- pydpm-xl: offendingSymbol: [@21,43:43='*',<18>,1:43] msg: extraneous input '*' expecting {BOOLEAN_LITERAL, NOT, MATCH, PLUS, MINUS, MAX_AGGR, MIN_AGGR, SUM, COUNT, AVG, MEDIAN, ABS, ISNULL, EXP, LN, SQRT, POWE…
- dpmcore: Unexpected error: "offendingSymbol: [@21,43:43='*',<18>,1:43] msg: extraneous input '*' expecting {BOOLEAN_LITERAL, NOT, MATCH, PLUS, MINUS, MAX_AGGR, MIN_AGGR, SUM, COUNT, AVG, MEDIAN, RANK, ABS, IS…

`max_aggr({tC_01.00, r0010}, ) > 0`

- dpm-xl: unexpected ')' where an operand is expected at position 28
- pydpm-xl: offendingSymbol: [@8,26:26=',',<37>,1:26] msg: extraneous input ',' expecting {'group by', RPAREN}
- dpmcore: Unexpected error: "offendingSymbol: [@8,26:26=',',<39>,1:26] msg: extraneous input ',' expecting {'group by', 'over', RPAREN}"

`{tC_01.00, r0010} in {[eba_qAE:qx2007]`

- dpm-xl: unterminated '{': no matching '}' at position 21
- pydpm-xl: offendingSymbol: [@13,38:37='<EOF>',<-1>,1:38] msg: missing CURLY_BRACKET_RIGHT at '<EOF>'
- dpmcore: Unexpected error: "offendingSymbol: [@13,38:37='<EOF>',<-1>,1:38] msg: missing CURLY_BRACKET_RIGHT at '<EOF>'"

