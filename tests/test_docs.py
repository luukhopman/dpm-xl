"""Run the examples in the documentation, so the docs cannot drift.

Every Markdown page under ``docs/`` (and the README) is checked:

* ``python`` blocks run in order in one namespace per page, from the
  repository root. A ``text`` block that directly follows a ``python`` block
  is its expected output and must match what the code prints.
* ``console`` blocks hold ``$ dpm-xl ...`` commands, each followed by its
  expected output (stdout and stderr, as a terminal shows them);
  ``$ echo $?`` prints the previous command's exit status.
* every line of a ``dpm-xl`` block must parse with
  :func:`dpmxl.parse_program`.

A block may carry code annotations: ``# (1)!`` comments, explained by the
numbered list right after the block. The list may stand between a ``python``
block and its output, and the comments are removed from ``console``
commands before they run.

``<!-- docs: skip -->`` on the line before a block leaves it out, and
``<!-- docs: invalid -->`` before a ``dpm-xl`` block expects a syntax error
on every line.

A table whose header starts with ``| Expression | Result |`` holds DPM-XL
examples and their results: each row's expression is evaluated against the
report in ``examples/language_report.py`` and must give the result shown,
as that file's ``evaluate`` formats it.

The language reference must cover the grammar: its index lists exactly the
names in :mod:`dpmxl.grammar`, each linked to an entry on the page, and its
examples use every keyword, function, operator, parameter type, period,
reference prefix and axis letter.

Pages that import ``polars``, ``dpmxbrl`` or ``dpmsynth`` are skipped when
those are not installed (``uv sync`` installs them with the ``docs`` group).

The docstring examples of every module run as doctests.
"""

from __future__ import annotations

import contextlib
import doctest
import functools
import importlib
import io
import os
import re
import runpy
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from dpmxl import DpmXlSyntaxError, parse_program
from dpmxl.cli import main
from dpmxl.grammar import (
    AXIS_LETTERS,
    FUNCTIONS,
    KEYWORDS,
    LITERAL_WORDS,
    OPERATORS,
    PARAMETER_TYPES,
    PUNCTUATION,
    REFERENCE_PREFIXES,
    SELECTION_KEYWORDS,
    TIME_PERIODS,
    WINDOW_KEYWORDS,
)
from dpmxl.parser import tokenize

ROOT = Path(__file__).parent.parent
PAGES = [
    *sorted(
        path for path in (ROOT / "docs").rglob("*.md") if ".snippets" not in path.parts
    ),
    ROOT / "README.md",
]
OPTIONAL_MODULES = {"polars", "dpmxbrl", "dpmsynth"}
FENCE = re.compile(r"^(?P<indent> *)```(?P<lang>[\w-]*)[^\n]*$")
MARKER = re.compile(r"^\s*<!-- docs: (?P<marker>[\w-]+) -->\s*$")
ANNOTATION = re.compile(r"\s*# \((?P<number>\d+)\)!?\s*$")
LIST_ITEM = re.compile(r"^\s*(?P<number>\d+)\.\s")


@dataclass
class Block:
    """One fenced code block of a page."""

    lang: str
    code: str
    line: int
    marker: str | None
    follows_python: bool


def blocks(path: Path) -> list[Block]:
    """Return the fenced code blocks of a Markdown page.

    Returns:
        list[Block]: Blocks in page order.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[Block] = []
    index = 0
    previous_end: int | None = None
    while index < len(lines):
        match = FENCE.match(lines[index])
        if not match:
            index += 1
            continue
        indent = len(match["indent"])
        start = index
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != "```":
            body.append(lines[index][indent:])
            index += 1
        marker_match = MARKER.match(lines[start - 1]) if start else None
        between = lines[previous_end + 1 : start] if previous_end is not None else []
        follows_python = (
            bool(found)
            and found[-1].lang == "python"
            and (
                all(not line.strip() for line in between)
                or (
                    bool(annotations(found[-1].code))
                    and annotation_list(between) is not None
                )
            )
        )
        found.append(
            Block(
                match["lang"],
                "\n".join(body) + "\n",
                start + 1,
                marker_match["marker"] if marker_match else None,
                follows_python,
            )
        )
        previous_end = index
        index += 1
    return found


def annotations(code: str) -> list[int]:
    """Return the numbers of the code annotations in a block, in order.

    Returns:
        list[int]: The numbers of the ``# (n)!`` comments.
    """
    return [
        int(match["number"])
        for line in code.splitlines()
        if (match := ANNOTATION.search(line))
    ]


def annotation_list(lines: list[str]) -> list[int] | None:
    """Return the item numbers of the annotation list in these lines.

    Returns:
        list[int] | None: The numbers of the list items, or None if the
        lines are not one numbered list (with indented continuation lines),
        surrounded by blank lines only.
    """
    numbers: list[int] = []
    for line in lines:
        if not line.strip():
            continue
        match = LIST_ITEM.match(line)
        if match:
            numbers.append(int(match["number"]))
        elif not numbers or not line[:1].isspace():
            return None
    return numbers or None


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


_VERSION = re.compile(r'("version": |name="version" value=)"[^"]*"')


def _versionless(text: str) -> str:
    """Normalize output, ignoring the version a JSON or JUnit document gives.

    Returns:
        str: The normalized text.
    """
    return _VERSION.sub(r'\1"…"', _normalize(text))


def _run_cli(command: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            status = main(shlex.split(command)[1:])
        except SystemExit as exit_:
            status = exit_.code if isinstance(exit_.code, int) else 0
    return status, output.getvalue()


def _check_console(block: Block, where: str) -> None:
    status = 0
    commands: list[tuple[str, list[str]]] = []
    for line in block.code.splitlines():
        if line.startswith("$ "):
            commands.append((ANNOTATION.sub("", line[2:]), []))
        elif commands:
            commands[-1][1].append(line)
        elif line.strip():
            pytest.fail(f"{where}: output before the first command")
    for command, expected in commands:
        if command == "echo $?":
            output = f"{status}\n"
        elif command.startswith("dpm-xl"):
            status, output = _run_cli(command)
        else:
            pytest.fail(f"{where}: only dpm-xl commands run in console blocks")
        assert _versionless(output) == _versionless("\n".join(expected)), (
            f"{where}: output of {command!r} differs"
        )


@pytest.mark.parametrize("path", PAGES, ids=lambda path: str(path.relative_to(ROOT)))
def test_page_examples(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    namespace: dict[str, object] = {"__name__": "__docs__"}
    last_output: str | None = None
    for block in blocks(path):
        where = f"{path.relative_to(ROOT)}:{block.line}"
        if block.marker == "skip":
            last_output = None
            continue
        if block.lang == "python":
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    exec(compile(block.code, where, "exec"), namespace)
            except ModuleNotFoundError as error:
                if error.name in OPTIONAL_MODULES:
                    pytest.skip(f"{error.name} is not installed")
                raise
            last_output = output.getvalue()
        elif block.lang == "text" and block.follows_python:
            assert last_output is not None
            assert _normalize(last_output) == _normalize(block.code), (
                f"{where}: printed output differs"
            )
            last_output = None
        elif block.lang == "console":
            _check_console(block, where)
        elif block.lang == "dpm-xl":
            for line in filter(str.strip, block.code.splitlines()):
                if block.marker == "invalid":
                    with pytest.raises(DpmXlSyntaxError):
                        parse_program(line)
                else:
                    parse_program(line)


def test_annotated_python_block_keeps_its_output(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "```python\n"
        "print(1)  # (1)!\n"
        "```\n\n"
        "1. Prints one,\n"
        "   as the output shows.\n\n"
        "```text\n1\n```\n\n"
        "```python\nprint(2)\n```\n\n"
        "1. Not an annotation list: the block has no annotations.\n\n"
        "```text\n2\n```\n",
        encoding="utf-8",
    )
    found = blocks(page)
    assert [block.lang for block in found] == ["python", "text", "python", "text"]
    assert [block.follows_python for block in found] == [False, True, False, False]
    assert annotations(found[0].code) == [1]


def test_annotation_list_needs_a_numbered_list() -> None:
    assert annotation_list(["", "1. One", "   more", "2. Two", ""]) == [1, 2]
    assert annotation_list(["Some text", "1. One"]) is None
    assert annotation_list(["   indented first"]) is None
    assert annotation_list(["", ""]) is None


def test_console_annotations_are_not_run() -> None:
    block = Block("console", "$ dpm-xl --version  # (1)!\n", 1, None, False)
    with pytest.raises(AssertionError, match="output of 'dpm-xl --version'"):
        _check_console(block, "page.md:1")


@pytest.mark.parametrize("path", PAGES, ids=lambda path: str(path.relative_to(ROOT)))
def test_code_annotations_are_explained(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for block in blocks(path):
        numbers = annotations(block.code)
        if not numbers:
            continue
        end = block.line + block.code.count("\n")
        after: list[str] = []
        for line in lines[end + 1 :]:
            if line.strip() and not LIST_ITEM.match(line) and not line[:1].isspace():
                break
            after.append(line)
        assert annotation_list(after) == numbers, (
            f"{path.relative_to(ROOT)}:{block.line}: annotations {numbers} need "
            "a numbered list with one item each right after the block"
        )


def test_markdown_copies_leave_out_presentation_markup() -> None:
    spec = spec_from_file_location("build_docs", ROOT / "scripts" / "build_docs.py")
    assert spec and spec.loader
    build_docs = module_from_spec(spec)
    spec.loader.exec_module(build_docs)
    text = (
        '<div class="grid cards" markdown>\n\n'
        "-   :lucide-rocket:{ .lg .middle } **Start**\n\n"
        "    [:lucide-arrow-right: Tutorial](start.md)\n\n"
        "</div>\n\n"
        "[Get started](start.md){ .md-button .md-button--primary }\n"
    )
    assert build_docs.plain(text) == (
        "-   **Start**\n\n    [Tutorial](start.md)\n\n[Get started](start.md)\n"
    )


# Result tables -------------------------------------------------------------

RESULT_HEADER = re.compile(r"^\|\s*Expression\s*\|\s*Result\s*\|")
CODE_CELL = re.compile(r"^(?P<ticks>`+) ?(?P<code>.*?) ?(?P=ticks)$")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _code(cell: str, where: str) -> str:
    match = CODE_CELL.match(cell)
    if match is None:
        pytest.fail(f"{where}: {cell!r} is not inline code")
    return match["code"]


def result_rows(path: Path) -> list[tuple[int, str, str]]:
    """Return ``(line, expression, result)`` for every result table row.

    Returns:
        list[tuple[int, str, str]]: The rows in page order.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    rows: list[tuple[int, str, str]] = []
    index = 0
    while index < len(lines):
        if not RESULT_HEADER.match(lines[index]):
            index += 1
            continue
        index += 2  # the header and its delimiter row
        while index < len(lines) and lines[index].startswith("|"):
            where = f"{path.relative_to(ROOT)}:{index + 1}"
            cells = _cells(lines[index])
            rows.append((index + 1, _code(cells[0], where), _code(cells[1], where)))
            index += 1
    return rows


@functools.cache
def _evaluate() -> Callable[[str], str]:
    module = runpy.run_path(str(ROOT / "examples" / "language_report.py"))
    return module["evaluate"]


RESULT_PAGES = [path for path in PAGES if result_rows(path)]


@pytest.mark.parametrize(
    "path", RESULT_PAGES, ids=lambda path: str(path.relative_to(ROOT))
)
def test_result_tables(path: Path) -> None:
    evaluate = _evaluate()
    wrong = [
        f"{path.relative_to(ROOT)}:{line}: {expression}\n"
        f"  shown:  {expected}\n  actual: {evaluate(expression)}"
        for line, expression, expected in result_rows(path)
        if evaluate(expression) != expected
    ]
    assert not wrong, "\n".join(wrong)


# Language reference coverage --------------------------------------------------

LANGUAGE = ROOT / "docs" / "reference" / "language.md"
QUICK_REFERENCE = ROOT / "docs" / "reference" / "quick-reference.md"
HEADING = re.compile(r"^#{1,6} (?P<text>.+?)(?: \{#(?P<id>[\w-]+)\})?$", re.MULTILINE)
ANCHOR = re.compile(r"\]\((?P<page>language\.md)?#(?P<anchor>[\w-]+)\)")
INDEX_ROW = re.compile(
    r"^\| (?P<name>`[^`]+`) \| (?P<kind>[a-z ]+) \| \[[^\]]+\]\(#(?P<anchor>[\w-]+)\) \|$",
    re.MULTILINE,
)
INDEX_KINDS = {
    "keyword": KEYWORDS,
    "window keyword": WINDOW_KEYWORDS,
    "selection option": SELECTION_KEYWORDS,
    "literal": LITERAL_WORDS,
    "parameter type": PARAMETER_TYPES,
    "period": TIME_PERIODS,
    "function": FUNCTIONS,
    "operator": OPERATORS,
    "punctuation": PUNCTUATION | {"{", "}"},
    "reference prefix": frozenset(REFERENCE_PREFIXES),
    "axis": AXIS_LETTERS,
}


def _slug(text: str) -> str:
    # Python-Markdown's toc slugify, on the heading's text without markup.
    text = re.sub(r"[^\w\s-]", "", text.replace("`", "")).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def _anchors(path: Path) -> set[str]:
    return {
        match["id"] or _slug(match["text"])
        for match in HEADING.finditer(path.read_text(encoding="utf-8"))
    }


def test_language_index_lists_the_grammar() -> None:
    found: dict[str, set[str]] = {kind: set() for kind in INDEX_KINDS}
    for match in INDEX_ROW.finditer(LANGUAGE.read_text(encoding="utf-8")):
        assert match["kind"] in found, f"unknown kind {match['kind']!r}"
        found[match["kind"]].add(match["name"].strip("`"))
    for kind, names in INDEX_KINDS.items():
        assert found[kind] == set(names), (
            f"{kind}: missing {sorted(set(names) - found[kind])}, "
            f"not in dpmxl.grammar {sorted(found[kind] - set(names))}"
        )


@pytest.mark.parametrize("path", [LANGUAGE, QUICK_REFERENCE], ids=lambda p: p.name)
def test_language_links_resolve(path: Path) -> None:
    anchors = {path.name: _anchors(path), LANGUAGE.name: _anchors(LANGUAGE)}
    text = path.read_text(encoding="utf-8")
    broken = sorted(
        {
            match.group()
            for match in ANCHOR.finditer(text)
            if match["anchor"] not in anchors[match["page"] or path.name]
        }
    )
    assert not broken


def _example_tokens() -> set[tuple[str, str]]:
    expressions = [expression for _, expression, _ in result_rows(LANGUAGE)]
    for block in blocks(LANGUAGE):
        if block.lang == "dpm-xl" and block.marker is None:
            expressions += filter(str.strip, block.code.splitlines())
    found: set[tuple[str, str]] = set()
    for expression in expressions:
        try:
            parse_program(expression)
        except DpmXlSyntaxError:
            continue  # an example of a syntax error uses no name
        for token in tokenize(expression):
            text = " ".join(token.text.split())
            if token.kind in {"axis", *REFERENCE_PREFIXES.values()}:
                text = token.text[0]
            elif token.kind != "period":
                text = text.casefold()
            found.add((token.kind, text))
    return found


def test_language_examples_use_every_name() -> None:
    found = _example_tokens()
    expected = {
        "keyword": KEYWORDS | WINDOW_KEYWORDS | SELECTION_KEYWORDS,
        "boolean or null": LITERAL_WORDS,
        "type": PARAMETER_TYPES,
        "period": TIME_PERIODS,
        "function": FUNCTIONS,
        "operator": OPERATORS,
        "reference prefix": frozenset(REFERENCE_PREFIXES),
        "axis": AXIS_LETTERS,
    }
    kinds = {
        "boolean or null": {"boolean", "null"},
        "reference prefix": set(REFERENCE_PREFIXES.values()),
    }
    missing = {
        kind: sorted(
            name
            for name in names
            if not any(
                (token_kind, name) in found for token_kind in kinds.get(kind, {kind})
            )
        )
        for kind, names in expected.items()
    }
    assert not any(missing.values()), missing


MODULES = [
    "dpmxl.ast",
    "dpmxl.cli",
    "dpmxl.evaluator",
    "dpmxl.explain",
    "dpmxl.grammar",
    "dpmxl.parser",
    "dpmxl.provider",
    "dpmxl.recordset",
    "dpmxl.references",
    "dpmxl.values",
    "dpmxl.columnar",
    "dpmxl.diagnostics",
    "dpmxl.rules",
    "dpmxl.module",
    "dpmxl.xbrl",
]


@pytest.mark.parametrize("name", MODULES)
def test_docstring_examples(name: str) -> None:
    if name == "dpmxl.columnar":
        pytest.importorskip("polars")
    if name == "dpmxl.xbrl":
        pytest.importorskip("dpmxbrl")
    module = importlib.import_module(name)
    finder = doctest.DocTestFinder(exclude_empty=True)
    runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
    cwd = Path.cwd()
    os.chdir(ROOT)
    try:
        for test in finder.find(module):
            runner.run(test)
    finally:
        os.chdir(cwd)
    result = runner.summarize(verbose=False)
    assert result.failed == 0
