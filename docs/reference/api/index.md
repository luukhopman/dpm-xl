---
description: The public Python API of dpm-xl, module by module, and the names re-exported from the dpmxl package.
---

# Python API

The public API is every name in the `__all__` of the modules below. Names
starting with an underscore are internal. The most used names are also
importable from the `dpmxl` package itself.

| Module | Purpose |
| --- | --- |
| [`dpmxl.evaluator`](evaluator.md) | Evaluation, preconditions, per-record outcomes, caches; thread safety. |
| [`dpmxl.explain`](explain.md) | Fills a failing record's formula with operand values. |
| [`dpmxl.provider`](provider.md) | The `DataProvider` protocol and the in-memory `MemoryProvider`. |
| [`dpmxl.rules`](rules.md) | Rule files: `Rule` with severity, `active` and modules, and `load_rules`. |
| [`dpmxl.module`](module.md) | Module files: `load_module`, `Module` and its tables, cells and rules. |
| [`dpmxl.dpm`](dpm.md) | Module files from an EBA DPM 2.0 database: `open_release` and `export_module`. |
| [`dpmxl.xbrl`](xbrl.md) | `ReportProvider` over a dpm-xbrl report and `check_report` (`xbrl` extra). |
| [`dpmxl.columnar`](columnar.md) | The same semantics on polars frames (`columnar` extra); the frame schema. |
| [`dpmxl.parser`](parser.md) | Tokenizer and recursive-descent parser. Nodes keep source spans. |
| [`dpmxl.ast`](ast.md) | Expression tree, selections, axis selectors and item literals. |
| [`dpmxl.grammar`](grammar.md) | Keywords, operators, function names and signatures; the TextMate grammar. |
| [`dpmxl.values`](values.md) | `Number` with interval tolerance, comparison and formatting. |
| [`dpmxl.recordset`](recordset.md) | Keyed record sets and the natural join used by every operator. |
| [`dpmxl.references`](references.md) | Static selections (with `with` context applied) and the templates `{v…}` variables test. |
| [`dpmxl.diagnostics`](diagnostics.md) | Positioned problems for editors: syntax, calls, tables and coordinates. |

The command line (`dpmxl.cli`) is documented in the [CLI reference](../cli.md).

## The `dpmxl` package

```python
import dpmxl

print(dpmxl.__all__)
```

```text
['AxisSelector', 'CellQuery', 'DataPoint', 'DataProvider', 'Diagnostic', 'DpmXlSyntaxError', 'Evaluation', 'EvaluationError', 'Evaluator', 'Explanation', 'Item', 'MemoryProvider', 'Node', 'Number', 'Operand', 'Outcome', 'Recordset', 'Reference', 'RuleResult', 'SelectionCache', 'SelectionSpec', 'TableLayout', 'UnsupportedError', 'Value', 'ValueSet', '__version__', 'axis_matcher', 'axis_matches', 'compare', 'diagnose', 'evaluate_rule', 'explain', 'format_value', 'is_template_code', 'iter_points', 'load_memory_provider', 'normalize_code', 'parse', 'parse_cached', 'parse_program', 'parse_selection', 'read_variable', 'references', 'reported_templates', 'tables', 'unique_points']
```

| Name | Defined in |
| --- | --- |
| [`evaluate_rule`][dpmxl.evaluator.evaluate_rule], [`RuleResult`][dpmxl.evaluator.RuleResult], [`Outcome`][dpmxl.evaluator.Outcome], [`Evaluation`][dpmxl.evaluator.Evaluation], [`Evaluator`][dpmxl.evaluator.Evaluator], [`SelectionCache`][dpmxl.evaluator.SelectionCache], [`parse_cached`][dpmxl.evaluator.parse_cached] | `dpmxl.evaluator` |
| [`explain`][dpmxl.explain.explain], [`Explanation`][dpmxl.explain.Explanation], [`Operand`][dpmxl.explain.Operand] | `dpmxl.explain` |
| [`DataProvider`][dpmxl.provider.DataProvider], [`MemoryProvider`][dpmxl.provider.MemoryProvider], [`TableLayout`][dpmxl.provider.TableLayout], [`CellQuery`][dpmxl.provider.CellQuery], [`DataPoint`][dpmxl.provider.DataPoint], [`axis_matcher`][dpmxl.provider.axis_matcher], [`axis_matches`][dpmxl.provider.axis_matches], [`normalize_code`][dpmxl.provider.normalize_code], [`read_variable`][dpmxl.provider.read_variable], [`is_template_code`][dpmxl.provider.is_template_code], [`load_memory_provider`][dpmxl.provider.load_memory_provider] | `dpmxl.provider` |
| [`parse`][dpmxl.parser.parse], [`parse_program`][dpmxl.parser.parse_program], [`parse_selection`][dpmxl.parser.parse_selection], [`DpmXlSyntaxError`][dpmxl.parser.DpmXlSyntaxError] | `dpmxl.parser` |
| [`Node`][dpmxl.ast.Node], [`Item`][dpmxl.ast.Item], [`SelectionSpec`][dpmxl.ast.SelectionSpec], [`AxisSelector`][dpmxl.ast.AxisSelector] | `dpmxl.ast` |
| [`Number`][dpmxl.values.Number], [`Value`][dpmxl.values.Value], [`ValueSet`][dpmxl.values.ValueSet], [`compare`][dpmxl.values.compare], [`format_value`][dpmxl.values.format_value] | `dpmxl.values` |
| [`Recordset`][dpmxl.recordset.Recordset], [`EvaluationError`][dpmxl.recordset.EvaluationError], [`UnsupportedError`][dpmxl.recordset.UnsupportedError], [`iter_points`][dpmxl.recordset.iter_points], [`unique_points`][dpmxl.recordset.unique_points] | `dpmxl.recordset` |
| [`references`][dpmxl.references.references], [`Reference`][dpmxl.references.Reference], [`tables`][dpmxl.references.tables], [`reported_templates`][dpmxl.references.reported_templates] | `dpmxl.references` |
| [`diagnose`][dpmxl.diagnostics.diagnose], [`Diagnostic`][dpmxl.diagnostics.Diagnostic] | `dpmxl.diagnostics` |

`dpmxl.__version__` is the installed version.
