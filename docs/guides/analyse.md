---
description: Read a rule without evaluating it - the expression tree, the selections with their with-context applied, the tables and the filing indicators it tests.
---

# Analyse rules statically

Before any report is loaded you can ask a rule what it reads: which tables
and cells, which filing indicators, which functions. That is how you index a
rule set by table, find the rules affected by a template change, or decide
which tables a report must contain.

## The expression tree

[`parse`][dpmxl.parser.parse] returns a tree of frozen dataclasses from
[`dpmxl.ast`](../reference/api/ast.md). Every node has a half-open source
`span`, so you can always show the original text of an operand.

```python
from dpmxl import parse

source = (
    "with {tC_01.00, c*, default: 0}: {r0010} = {r0020} + sum({tC_02.00, r0010-0050})"
)
tree = parse(source)
comparison = tree.body
print(type(tree).__name__, type(comparison).__name__, comparison.op)
print(source[slice(*comparison.right.span)])
```

```text
With Binary =
{r0020} + sum({tC_02.00, r0010-0050})
```

[`walk`][dpmxl.ast.walk] yields every node, depth first, and
[`children`][dpmxl.ast.children] a node's direct children (including the
`default` of a selection, a `with` context and a typed parameter):

```python
from dpmxl.ast import Call, walk

print([node.name for node in walk(tree) if isinstance(node, Call)])
```

```text
['sum']
```

The [language reference](../reference/language.md) names the node each
construct parses to. Analytic calls such as `rank(x over (…))` are
`Analytic` nodes, not `Call`s. [`parse_program`][dpmxl.parser.parse_program]
returns a `Program` whose `statements` are expressions, `Assignment`s
(`name := e`) and `PersistentAssignment`s (`{target} <- e`).

## Selections with their context

A selection inside `with` inherits the context's table, axes and options.
[`references`][dpmxl.references.references] returns every selection completed
by its context, as [`Reference`][dpmxl.references.Reference] objects in source
order:

```python
from dpmxl import references

source = "with {tC_01.00, c*, default: 0}: {r0010} = {r0020} + {g_G1, r0010} + {o_v123}"
for reference in references(parse(source)):
    print(
        f"{reference.kind:12} {reference.code:8} {reference.spec.text():36} {source[slice(*reference.span)]}"
    )
```

```text
table        C_01.00  {tC_01.00, r0010, c*, default: 0}    {r0010}
table        C_01.00  {tC_01.00, r0020, c*, default: 0}    {r0020}
table_group  G1       {gG1, r0010, c*, default: 0}         {g_G1, r0010}
operation    v123     {ov123, c*, default: 0}              {o_v123}
```

`kind` is `table`, `table_group` or `operation`; for the latter two
`spec.table` is `None` and `code` names the group or operation. Typed
parameters (`{p_Name, …}`) are not selections and are not listed; targets of
persistent assignments are.

## Tables and filing indicators

[`tables`][dpmxl.references.tables] lists the distinct table codes the
cell selections read. Given a provider with a `table_group` method, a group
read counts as reading every table of the group:

```python
from dpmxl import MemoryProvider, tables

tree = parse(source)
print(tables(tree))
print(tables(tree, MemoryProvider([], {}, table_groups={"G1": ["C_03.00", "C_04.00"]})))
```

```text
('C_01.00',)
('C_01.00', 'C_03.00', 'C_04.00')
```

[`reported_templates`][dpmxl.references.reported_templates] lists the
templates a rule tests with `{v_…}`, typically in its precondition:

```python
from dpmxl import reported_templates

print(reported_templates(parse("{v_C_01.00} and not {v_C_02.00}")))
```

```text
('C_01.00', 'C_02.00')
```

## Index a rule set by table

```python
import json
from collections import defaultdict
from pathlib import Path

from dpmxl import parse_program

by_table = defaultdict(list)
for rule in json.loads(Path("examples/rules.json").read_text()):
    for table in tables(parse_program(rule["expression"])):
        by_table[table].append(rule["code"])
print(dict(by_table))
```

```text
{'C_01.00': ['v0001', 'v0003'], 'C_27.00': ['v0002'], 'C_99.00': ['v0004']}
```

`dpm-xl check --references` prints the same selections for a rule file on the
command line ([CLI reference](../reference/cli.md#dpm-xl-check)).
