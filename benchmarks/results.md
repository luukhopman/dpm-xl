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
| rank over a partition | accepted | rejected | accepted |
| windowed aggregate | accepted | rejected | accepted |
| statements with := | accepted | rejected | rejected |
| persistent assignment <- | accepted | rejected | accepted |
| operation reference {o...} | accepted | accepted | accepted |
| set operators and literals | accepted | rejected | accepted |
| typed parameter {p...} | accepted | rejected | accepted |
| text concatenation & | accepted | accepted | accepted |
| date functions | accepted | rejected | accepted |
| date() and date literals | accepted | rejected | accepted |
| table group {g...} | accepted | accepted | accepted |
| annualise | accepted | rejected | accepted |

#### Syntax error messages

`{tC_01.00, r0010, c0010} >=`

- dpm-xl: expression ends where an operand is expected at position 27
- pydpm-xl: offendingSymbol: [@11,27:26='<EOF>',<-1>,1:27] msg: mismatched input '<EOF>' expecting {BOOLEAN_LITERAL, NOT,…
- dpmcore: Unexpected error: "offendingSymbol: [@11,27:26='<EOF>',<-1>,1:27] msg: mismatched input '<EOF>' expecting {BO…

`with {tC_01.00, c0010}: {r0010} = {r0020} +`

- dpm-xl: expression ends where an operand is expected at position 43
- pydpm-xl: offendingSymbol: [@21,43:42='<EOF>',<-1>,1:43] msg: mismatched input '<EOF>' expecting {BOOLEAN_LITERAL, NOT,…
- dpmcore: Unexpected error: "offendingSymbol: [@21,43:42='<EOF>',<-1>,1:43] msg: mismatched input '<EOF>' expecting {BO…

