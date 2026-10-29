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
LINKS = DOCS / ".snippets" / "links.md"
SNIPPET = re.compile(r'^(?P<indent> *)--8<-- "(?P<path>[^"]+)"$', re.MULTILINE)
DIRECTIVE = re.compile(r"^::: (?P<name>[\w.]+)\n(?:(?: {4}.*)?\n)*", re.MULTILINE)
CROSS_REFERENCE = re.compile(r"\[([^\]\n]+)\]\[(?:[\w]+\.[\w.]+)?\]")
MARKER = re.compile(r"^<!-- docs: [\w-]+ -->\n", re.MULTILINE)
FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
ICON = re.compile(
    r":(?:lucide|material|fontawesome|octicons|simple)-[\w-]+:(?:\{[^}\n]*\})? ?"
)
ATTRIBUTES = re.compile(r"(?<=\))\{ [^}\n]*\}")
HTML_BLOCK = re.compile(r"^</?div\b[^>\n]*>\n\n?", re.MULTILINE)
TOOLKIT = {
    "dpm-xl": "Parse and evaluate DPM-XL validation rules.",
    "dpm-xbrl": "Read, write and check xBRL-CSV and XBRL-XML reports.",
    "dpm-synth": "Generate test reports that satisfy DPM-XL rules.",
}
TOUR = "https://luukhopman.github.io/dpm-xl/guides/toolkit-tour.md"


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
                if not value.startswith("https://"):  # links to other sites
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


def related(name: str) -> str:
    """Return the llms.txt section that links the other packages of the toolkit.

    Returns:
        str: A ``## Related`` section, the same on every site but for ``name``.
    """
    links = [
        f"- [{package}](https://luukhopman.github.io/{package}/llms.txt): {text}"
        for package, text in TOOLKIT.items()
        if package != name
    ]
    links.append(
        f"- [Toolkit tour]({TOUR}): Generate a report with dpm-synth, read it "
        "with dpm-xbrl, then evaluate and explain its rules with dpm-xl."
    )
    return "## Related\n\nThe other packages of the dpm toolkit:\n\n" + (
        "\n".join(links) + "\n"
    )


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


def _parameters(parameters: griffe.Parameters) -> str:
    """Render parameters as Python source, with ``*`` and ``/`` markers.

    Returns:
        str: The parameter list without parentheses.
    """
    parts: list[str] = []
    star = False
    for index, parameter in enumerate(parameters):
        if index == 0 and parameter.name in {"self", "cls"}:
            continue
        kind = parameter.kind
        if kind is griffe.ParameterKind.keyword_only and not star:
            parts.append("*")
            star = True
        prefix = ""
        if kind is griffe.ParameterKind.var_positional:
            prefix, star = "*", True
        elif kind is griffe.ParameterKind.var_keyword:
            prefix = "**"
        text = prefix + parameter.name
        if parameter.annotation is not None:
            text += f": {parameter.annotation}"
        if parameter.default is not None:
            text += (
                f" = {parameter.default}"
                if parameter.annotation
                else f"={parameter.default}"
            )
        parts.append(text)
        following = list(parameters)[index + 1 :]
        if kind is griffe.ParameterKind.positional_only and not any(
            item.kind is griffe.ParameterKind.positional_only for item in following
        ):
            parts.append("/")
    return ", ".join(parts)


def _signature(obj: griffe.Object | griffe.Alias, source: str) -> str:
    if obj.is_function:
        parameters = _parameters(obj.parameters)
        returns = f" -> {obj.returns}" if obj.returns else ""
        return f"def {obj.name}({parameters}){returns}"
    bases = ", ".join(str(base) for base in obj.bases)
    init = obj.members.get("__init__")
    parameters = ""
    if init is not None and init.is_function:
        parameters = _parameters(init.parameters)
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


def plain(text: str) -> str:
    """Remove the site's presentation markup: icons, attribute lists, divs.

    Returns:
        str: The text with card grids, buttons and badges as plain Markdown.
    """
    text = ICON.sub("", text)
    text = ATTRIBUTES.sub("", text)
    return HTML_BLOCK.sub("", text)


def markdown_copy(text: str, package: griffe.Module) -> str:
    """Turn a source page into plain Markdown for agents.

    Returns:
        str: The page with snippets included, directives expanded,
        cross-references reduced to their text, test markers and
        presentation markup removed, and the shared link targets appended.
    """
    _, text = front_matter(text)

    def include(match: re.Match[str]) -> str:
        content = (ROOT / match["path"]).read_text(encoding="utf-8")
        return "\n".join(match["indent"] + line for line in content.splitlines())

    text = SNIPPET.sub(include, text)
    text = DIRECTIVE.sub(lambda match: render_module(match["name"], package), text)
    text = MARKER.sub("", text)
    text = CROSS_REFERENCE.sub(r"\1", text)
    text = plain(text)
    # Reference-style links such as [dpm-xbrl] resolve against the shared
    # link list, which the site appends to every page.
    return text.rstrip("\n") + "\n\n" + LINKS.read_text(encoding="utf-8")


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
    project = sections.pop("Project", [])
    for section, links in sections.items():
        index.append(f"## {section}\n\n" + "\n".join(links) + "\n")
    index.append(related(config["site_name"]))
    if project:
        index.append("## Optional\n\n" + "\n".join(project) + "\n")
    (SITE / "llms.txt").write_text("\n".join(index), encoding="utf-8")
    (SITE / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")
    print(f"llms.txt, llms-full.txt and {len(full)} Markdown pages written to site/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
