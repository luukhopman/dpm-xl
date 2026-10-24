---
description: Evaluate the rules of one report concurrently, with the caches and providers that are safe to share across threads.
---

# Run rules in threads

`evaluate_rule` and `evaluate_rule_columnar` may run concurrently on one
report. What may be shared between threads:

| Object | Safe to share | Notes |
| --- | --- | --- |
| [`parse_cached`][dpmxl.evaluator.parse_cached] | yes | Parsed trees are immutable and serve every report. |
| [`SelectionCache`][dpmxl.evaluator.SelectionCache] | yes | Two threads that miss the same selection at once may both build it; either result is kept. Use one per report. |
| [`FrameCache`][dpmxl.columnar.FrameCache] | yes | Builds each selection once while other threads asking for it wait. Use one per report. |
| [`MemoryProvider`][dpmxl.provider.MemoryProvider] | yes | Read-only after construction. |
| Your provider | if it is safe to read concurrently | A provider with a database connection per instance is not; use a connection pool or one provider per thread. |
| [`Evaluator`][dpmxl.evaluator.Evaluator] | no | One per evaluation; `evaluate_rule` creates its own. |

The reference evaluator is pure Python, so threads help it only when your
provider waits on I/O. The columnar evaluator spends its time in polars,
which releases the GIL, so threads use several cores.

## A rule run on a thread pool

```python
from concurrent.futures import ThreadPoolExecutor

from dpmxl import MemoryProvider, Number, SelectionCache, TableLayout, evaluate_rule

provider = MemoryProvider(
    [TableLayout("C_01.00", rows=("0010", "0020", "0030"), columns=("0010", "0020"))],
    {
        ("C_01.00", row, column, None, ()): Number.of(amount, 0)
        for (row, column), amount in {
            ("0010", "0010"): 100,
            ("0020", "0010"): 60,
            ("0030", "0010"): 40,
            ("0010", "0020"): 1204,
            ("0020", "0020"): 1180,
            ("0030", "0020"): 31,
        }.items()
    },
)
rules = {
    "v0001": "with {tC_01.00, c*, default: 0, interval: true}: {r0010} = {r0020} + {r0030}",
    "v0002": "with {tC_01.00, c0010}: {r0020} >= {r0030}",
    "v0003": "{tC_01.00, r0010, c0020} < 1000",
}
cache = SelectionCache()  # one per report, shared by every thread


def run(code):
    return code, evaluate_rule(rules[code], provider, cache=cache).status


with ThreadPoolExecutor(max_workers=4) as pool:
    for code, status in pool.map(run, rules):
        print(code, status)
```

```text
v0001 failed
v0002 passed
v0003 failed
```

`pool.map` returns results in submission order, whatever order the threads
finish in.

## Columnar rules on threads

The same pattern with the columnar evaluator and a shared `FrameCache`,
falling back to the reference evaluator for rules it does not cover (see
[Evaluate large reports](columnar.md)):

```python
from dpmxl.columnar import (
    ColumnarUnsupported,
    FrameCache,
    PointsFrameProvider,
    evaluate_rule_columnar,
)

frames = FrameCache()
frame_provider = PointsFrameProvider(provider)


def run_columnar(code):
    try:
        return code, evaluate_rule_columnar(
            rules[code], frame_provider, cache=frames
        ).status
    except ColumnarUnsupported:
        return code, evaluate_rule(rules[code], provider, cache=cache).status


with ThreadPoolExecutor(max_workers=4) as pool:
    print(dict(pool.map(run_columnar, rules)))
```

```text
{'v0001': 'failed', 'v0002': 'passed', 'v0003': 'failed'}
```

## Processes

For many reports at once, evaluate each report in its own process (for
example with `ProcessPoolExecutor`) and use threads within a report. Parsed
trees, caches and providers are per process; `parse_cached` warms up again
in each.
