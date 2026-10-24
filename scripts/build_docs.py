"""Build the documentation site, with Markdown copies for AI agents.

Run ``uv run python scripts/build_docs.py``. It builds ``site/`` with
``zensical build --strict`` (any warning, such as a broken link or an
unresolved API reference, fails the build), then adds, following
https://llmstxt.org:

* ``<page>.md``: a Markdown copy of every page, next to the HTML, with
  API reference directives (``::: dpmxl.module``) expanded into signatures
  and docstrings;
* ``llms.txt``: an index of the pages with one-line descriptions;
* ``llms-full.txt``: every page's Markdown copy, concatenated in nav order.
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import griffe

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "zensical.toml"
DOCS = ROOT / "docs"
SITE = ROOT / "site"
SNIPPET = re.compile(r'^(?P<indent> *)--8<-- "(?P<path>[^"]+)"$', re.MULTILINE)
DIRECTIVE = re.compile(r"^::: (?P<name>[\w.]+)\n(?:(?: {4}.*)?\n)*", re.MULTILINE)
CROSS_REFERENCE = re.compile(r"\[([^\]\n]+)\]\[[\w.]*\]")
MARKER = re.compile(r"^<!-- docs: [\w-]+ -->\n", re.MULTILINE)
FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


def nav_pages(nav: list[object], section: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(section, page path)`` for every page of the nav, in order.

    Yields:
        tuple[str, str]: The top-level section title and the page path.
    """
    for entry in nav:
        if isinstance(entry, str):
            yield section, entry
            continue
        assert isinstance(entry, dict)
        for title, value in entry.items():
            if isinstance(value, str):
                yield section or title, value
            else:
                yield from nav_pages(value, section or title)


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split simple ``key: value`` front matter from a page.

    Returns:
        tuple[dict[str, str], str]: The front matter and the page body.
    """
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match["body"].splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').replace('\\"', '"')
    return meta, text[match.end() :]


def render_object(obj: griffe.Object | griffe.Alias, level: int) -> str:
    """Render one documented object as Markdown.

    Returns:
        str: A heading, the signature and the docstring.
    """
    heading = "#" * level
    parts = [f"{heading} `{obj.path}`\n"]
    if obj.is_function or obj.is_class:
        source = obj.source if obj.is_function else ""
        signature = _signature(obj, source)
        if signature:
            parts.append(f"```python\n{signature}\n```\n")
    elif obj.is_attribute:
        value = f" = {obj.value}" if obj.value is not None else ""
        annotation = f": {obj.annotation}" if obj.annotation else ""
        parts.append(f"```python\n{obj.name}{annotation}{value}\n```\n")
    if obj.docstring:
        parts.append(inspect.cleandoc(obj.docstring.value) + "\n")
    if obj.is_class:
        for member in obj.members.values():
            if member.name.startswith("_") or member.is_alias:
                continue
            if member.is_attribute and not member.docstring:
                continue
            parts.append(render_object(member, level + 1))
    return "\n".join(parts)


def _signature(obj: griffe.Object | griffe.Alias, source: str) -> str:
    if obj.is_function:
        parameters = ", ".join(str(parameter) for parameter in obj.parameters)
        returns = f" -> {obj.returns}" if obj.returns else ""
        return f"def {obj.name}({parameters}){returns}"
    bases = ", ".join(str(base) for base in obj.bases)
    init = obj.members.get("__init__")
    parameters = ""
    if init is not None and init.is_function:
        parameters = ", ".join(
            str(parameter) for parameter in init.parameters if parameter.name != "self"
        )
        return f"class {obj.name}({parameters})" + (
            f"  # bases: {bases}" if bases else ""
        )
    return f"class {obj.name}({bases})" if bases else f"class {obj.name}"


def render_module(path: str, package: griffe.Module) -> str:
    """Render a module's docstring and public names as Markdown.

    Returns:
        str: The module reference.
    """
    module = package[path.split(".", 1)[1]] if "." in path else package
    parts = []
    if module.docstring:
        parts.append(inspect.cleandoc(module.docstring.value) + "\n")
    for name in module.exports or ():
        parts.append(render_object(module[name], 2))
    return "\n".join(parts)


def markdown_copy(text: str, package: griffe.Module) -> str:
    """Turn a source page into plain Markdown for agents.

    Returns:
        str: The page with snippets included, directives expanded,
        cross-references reduced to their text and test markers removed.
    """
    _, text = front_matter(text)

    def include(match: re.Match[str]) -> str:
        content = (ROOT / match["path"]).read_text(encoding="utf-8")
        return "\n".join(match["indent"] + line for line in content.splitlines())

    text = SNIPPET.sub(include, text)
    text = DIRECTIVE.sub(lambda match: render_module(match["name"], package), text)
    text = MARKER.sub("", text)
    return CROSS_REFERENCE.sub(r"\1", text)


def main() -> int:
    """Build the site and the agent files.

    Returns:
        int: The exit status.
    """
    build = subprocess.run(
        [sys.executable, "-m", "zensical", "build", "--strict", "--clean"],
        cwd=ROOT,
        check=False,
    )
    if build.returncode:
        return build.returncode
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["project"]
    site_url = config["site_url"]
    package = griffe.load(
        "dpmxl", search_paths=[str(ROOT / "src")], docstring_parser="google"
    )
    sections: dict[str, list[str]] = {}
    full = []
    for section, page in nav_pages(config["nav"]):
        source = (DOCS / page).read_text(encoding="utf-8")
        meta, _ = front_matter(source)
        copy = markdown_copy(source, package)
        target = SITE / page
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(copy, encoding="utf-8")
        title = next(
            (line[2:].strip() for line in copy.splitlines() if line.startswith("# ")),
            page,
        )
        description = meta.get("description", "")
        link = f"- [{title}]({site_url}{page})" + (
            f": {description}" if description else ""
        )
        sections.setdefault(section, []).append(link)
        full.append(f"<!-- source: {site_url}{page} -->\n\n{copy.strip()}\n")
    index = [
        f"# {config['site_name']}\n",
        f"> {config['site_description']}. dpm-xl parses DPM-XL expressions, "
        "evaluates them against report data supplied through a small provider "
        "interface, with EBA interval arithmetic and null logic, and explains "
        "each failing record in plain numbers.\n",
        "Python 3.11+, no runtime dependencies (`pip install dpm-xl`; the "
        "`columnar` extra adds a polars evaluator). Independent project, not "
        "affiliated with or endorsed by the EBA. "
        f"Everything below in one file: {site_url}llms-full.txt\n",
    ]
    for section, links in sections.items():
        name = "Optional" if section == "Project" else section
        index.append(f"## {name}\n\n" + "\n".join(links) + "\n")
    (SITE / "llms.txt").write_text("\n".join(index), encoding="utf-8")
    (SITE / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")
    print(f"llms.txt, llms-full.txt and {len(full)} Markdown pages written to site/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
