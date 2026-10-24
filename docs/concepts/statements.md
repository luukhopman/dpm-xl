---
description: Scripts of several statements, temporary assignments with := and persistent assignments with <-.
---

# Statements and assignments

A rule is usually one expression. DPM-XL also allows a script: statements
separated by `;`, with two kinds of assignment.

| Statement | Meaning |
| --- | --- |
| `expression` | An expression, with an optional `with` context. |
| `name := expression` | A temporary assignment: `name` holds the expression's records for later statements. |
| `{target} <- expression` | A persistent assignment: the value is computed and returned in `RuleResult.assignments`. Targets are cell selections such as `{tT, r0010, c0010}` or parameters such as `{vX}`. |

Statements run in order; the **last** one gives the rule's records and
verdict. The last statement needs no `;`, and a trailing `;` is allowed.

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

provider = MemoryProvider(
    [TableLayout("T", rows=("0010", "0020"), columns=("0010", "0020"))],
    {
        ("T", "0010", "0010", None, ()): Number.of(10, 0),
        ("T", "0020", "0010", None, ()): Number.of(4, 0),
        ("T", "0010", "0020", None, ()): Number.of(1, 0),
        ("T", "0020", "0020", None, ()): Number.of(4, 0),
    },
)
script = "d := with {tT, c*}: {r0010} - {r0020}; d > 0"
result = evaluate_rule(script, provider)
print(
    result.status, [(dict(outcome.key), outcome.passed) for outcome in result.outcomes]
)
```

```text
failed [({'c': '0010'}, True), ({'c': '0020'}, False)]
```

A temporary keeps the records of its expression, keys included. In later
statements its name wins over a report parameter of that name and loses to a
key component inside a clause. The rule's context, temporaries and
assignments do not reach operations referenced with `{o_…}`, which are
evaluated on their own.

## Persistent assignments

```python
result = evaluate_rule(
    "{tT, r0010, c0010} <- {tT, r0020, c0010} * 2; {tT, r0010, c0010} = 10", provider
)
print(result.status)
for target, recordset in result.assignments.items():
    print(target, [record.value for record in recordset.records.values()])
```

```text
passed
{tT, r0010, c0010} [Number(value=Decimal('8'), tolerance=Decimal('0'))]
```

Nothing is written to the report: the last statement still reads the
reported 10. The assignment's value is for the caller, keyed by the target's
normalized DPM-XL text.

## Parsing scripts

[`parse_program`][dpmxl.parser.parse_program] parses a script into a
`Program`; [`parse`][dpmxl.parser.parse] accepts one expression (with an
optional trailing `;`) and says so when given a script. `evaluate_rule`,
the columnar fallback and `dpm-xl check` accept scripts.

Outside clauses `<-` is the assignment, so compare with a negated operand as
`a < -b`. Inside `[…]` clauses, as in the grammar, `<-` reads `< -`.

The columnar evaluator hands every script with assignments to the reference
evaluator.
