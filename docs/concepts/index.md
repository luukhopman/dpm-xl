---
description: The semantics of DPM-XL as dpm-xl implements them, and the specification they follow.
---

# Concepts

How DPM-XL rules are evaluated. These pages explain the semantics; the
[language reference](../reference/language.md) lists every construct.

<div class="grid cards" markdown>

-   :lucide-key-round:{ .lg .middle } [**Records and keys**](records-and-keys.md)

    ---

    Selections yield keyed records; operators join them.

-   :lucide-layers:{ .lg .middle } [**Defaults across keys**](defaults.md)

    ---

    How an operand with a default fills in keys other operands have.

-   :lucide-circle-slash:{ .lg .middle } [**Null logic**](null.md)

    ---

    Defaults, null propagation, three-valued logic and errors confined to
    their record.

-   :lucide-ruler:{ .lg .middle } [**Interval arithmetic**](intervals.md)

    ---

    Reported precision as intervals, and the gap in explanations.

-   :lucide-flag:{ .lg .middle } [**Preconditions and results**](results.md)

    ---

    The rule statuses and what a result holds.

-   :lucide-list-ordered:{ .lg .middle } [**Statements and assignments**](statements.md)

    ---

    Scripts with `:=` and `<-`.

-   :lucide-braces:{ .lg .middle } [**Sets**](sets.md)

    ---

    Set literals, parameters, operators and `in`.

-   :lucide-sigma:{ .lg .middle } [**Aggregates and analytic functions**](analytics.md)

    ---

    `group by`, `rank` and windows.

-   :lucide-calendar:{ .lg .middle } [**Time**](time.md)

    ---

    Dates, `time_shift` and `annualise`.

-   :lucide-link:{ .lg .middle } [**Parameters, operations and table groups**](references.md)

    ---

    Everything a rule reads besides cells.

</div>

## Sources

These semantics follow the DPM-XL specification and the interval
arithmetic rule of the EBA Filing Rules; the versions, and where dpm-xl
reads a rule differently so that EBA rules keep their meaning, are on
[standards and conformance](../reference/standards.md).
