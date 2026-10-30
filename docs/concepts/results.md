---
description: The rule statuses, record counts and severities, what preconditions do, and what a RuleResult and its outcomes hold.
---

# Preconditions and results

[`evaluate_rule(expression, provider, *, precondition=None)`][dpmxl.evaluator.evaluate_rule]
never raises for a bad rule or bad data. It returns a
[`RuleResult`][dpmxl.evaluator.RuleResult] whose status is one of the first
five below; [`evaluate_rules`][dpmxl.rules.evaluate_rules], `check_report`
and the CLI add `skipped`. Other pages link to this list.

| Status | When |
| --- | --- |
| `passed` | At least one record is true and none is false. |
| `failed` | At least one record is false. |
| `not_applicable` | The precondition is not met, or no record could be evaluated (all null). |
| `error` | A syntax error, an unknown table, a type mismatch, a rule that yields values instead of Booleans, or a run-time error (such as division by zero) in a record that reaches the result. |
| `unsupported` | The rule needs something the provider does not offer (a `time_shift` report, a `{o_…}` operation or a `{g_…}` table group), or a function dpm-xl does not know. |
| `skipped` | The rule is inactive (`"active": false`) or is for another module, so it is not evaluated. |

```python
from dpmxl import MemoryProvider, Number, TableLayout, evaluate_rule

provider = MemoryProvider(
    [TableLayout("T", rows=("0010",), columns=("0010",))],
    {("T", "0010", "0010", None, ()): Number.of(10, 0)},
)
for expression, precondition in [
    ("{tT, r0010, c0010} > 0", "{v_T}"),
    ("{tT, r0010, c0010} > 0", "{v_X}"),
    ("{tT, r0010, c0010} >", None),
    ("{tX, r0010} > 0", None),
    ('{tT, r0010, c0010} > "a"', None),
    ("{tT, r0010, c0010} + 1", None),
    ("{o_X} > 0", None),
    ("foo({tT, r0010, c0010}) > 0", None),
]:
    result = evaluate_rule(expression, provider, precondition=precondition)
    print(f"{result.status:15} {result.message}")
```

```text
passed          None
not_applicable  precondition not met
error           expression ends where an operand is expected at position 20
error           unknown table X
error           cannot compare number with string using '>'
error           rule yields number values, not booleans
unsupported     operation X needs a provider that resolves operations
unsupported     unknown function 'foo'
```

`message` says why the status is `error`, `unsupported` or
`not_applicable`; its wording may improve in minor releases, the statuses
may not.

## Preconditions

A precondition is an expression, usually filing-indicator tests such as
`{v_C_01.00}` or `{v_C_01.00} and {v_C_02.00}`. The rule applies only when the
precondition yields at least one true record; otherwise the result is
`not_applicable` without evaluating the rule. A precondition is evaluated on
all records, also when `only_keys` restricts the rule.

`{v_TABLE}` asks the provider's `table_reported(table)` when `TABLE` is a
template code ([Variables](references.md#variables)). `MemoryProvider`
answers from its `reported` codes (by default every table with a value) and
from each layout's `template`.

## What a result holds

| Field | Content |
| --- | --- |
| `status`, `message` | As above. |
| `outcomes` | One [`Outcome`][dpmxl.evaluator.Outcome] per record: `key` (such as `{'c': '0020'}`), `passed` (`True`, `False`, or `None` when not evaluated) and `points`, the distinct cells it was computed from. |
| `failures` | The outcomes whose `passed` is `False`. |
| `counts` | `{'passed': n, 'failed': n, 'null': n}`. |
| `evaluation` | The trace [`explain`][dpmxl.explain.explain] reads; `None` for syntax and provider errors. |
| `assignments` | Results of persistent assignments (`{target} <- value`) by target text, such as `{tT, r0010, c0010}` ([Statements](statements.md)). |
| `notes` | Remarks the evaluator made along the way. |

`DataPoint.ref` in `outcome.points` is whatever identity your provider gave
the cell, so a user interface can highlight it
([Explain failures in a UI](../guides/explain.md)).

## Records and counts

A rule has one record per key, and each record is true (passed), false
(failed) or null. A null record could not be evaluated, because a cell it
needs was not reported and has no `default` ([Null logic](null.md)).
`counts` and the CLI's `records:` line count the three:
`records: 1 passed, 1 failed, 0 null`.

A rule whose every record is null is `not_applicable`, just like one whose
precondition is not met. In an empty or incomplete report, a rule can
therefore show `not_applicable` because the data it checks is missing;
`message` tells the two apart.

## Severity

A validation rule has a severity, `error` or `warning`, from its rule file
or module file (the DPM gives it for EBA rules); `error` when none is
given. The status does not depend on it: a failing `warning` rule is
`failed`, and the CLI shows it as `failed (warning)`. The severity decides
whether a failure fails a run: by default only `error` rules do, and
`--fail-on warning` makes warnings count too.

The [filing rules](https://luukhopman.github.io/dpm-xbrl/) that dpm-xbrl
checks, on the file rather than its values, have a severity of their own:
`error` where the EBA filing rules say MUST, `warning` where they say
SHOULD. `dpm-xl check-report` lists both kinds and applies `--fail-on` to
both. How each command's exit status follows from this is in the
[CLI reference](../reference/cli.md#exit-statuses).
