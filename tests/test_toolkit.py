"""Keep the three packages of the dpm toolkit presented as one.

dpm-xl, dpm-xbrl and dpm-synth carry this file unchanged. It checks:

* the toolkit block: ``CANONICAL`` with the row of this package marked must
  equal the README's Toolkit section. ``CANONICAL_SHA256`` is the same in the
  three repositories, so the text changes in all three or not at all;
* the shared docs files: the toolkit cards (``docs/.snippets/toolkit-cards.md``,
  which the docs home page and the toolkit page include), the toolkit page,
  the glossary and the stylesheet are the same in the three repositories
  (``SHARED_SHA256``), and so are the search and social metadata: the
  templates in ``overrides/``, ``scripts/seo.py`` and ``tests/test_site.py``;
* the README skeleton: the same sections in the same order;
* the independence statement, directly under the pitch of the README and of
  the docs home page;
* the docs footer and the Toolkit section of the docs navigation.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
NAME = PYPROJECT["project"]["name"]
PACKAGES = ("dpm-xl", "dpm-xbrl", "dpm-synth")
SITE = "https://luukhopman.github.io/{}/"

CANONICAL = """\
**Part of the dpm toolkit**, three Python packages that work together:

| Package | What it does |
| :-- | :-- |
| <a href="https://luukhopman.github.io/dpm-xl/"><img src="https://luukhopman.github.io/dpm-xl/assets/logo.svg" alt="dpm-xl" height="32"></a> | Parse and evaluate DPM-XL validation rules |
| <a href="https://luukhopman.github.io/dpm-xbrl/"><img src="https://luukhopman.github.io/dpm-xbrl/assets/logo.svg" alt="dpm-xbrl" height="32"></a> | Read, write and check xBRL-CSV and XBRL-XML reports |
| <a href="https://luukhopman.github.io/dpm-synth/"><img src="https://luukhopman.github.io/dpm-synth/assets/logo.svg" alt="dpm-synth" height="32"></a> | Generate test reports that satisfy DPM-XL rules |

The [toolkit tour](https://luukhopman.github.io/dpm-xl/guides/toolkit-tour/)
takes one report through all three: generated with dpm-synth, read with
dpm-xbrl, then evaluated and explained with dpm-xl.
"""
CANONICAL_SHA256 = "c6fcdd7cb33e47c0d910dd0dd109d9c017a570095d07b94c3c902fdddc8d022e"

SHARED_SHA256 = {
    "docs/.snippets/toolkit-cards.md": (
        "0b0b4aeff0f85ffe10e7856854d0e82014341f1564be3ae7f68f6075d5c36381"
    ),
    "docs/.snippets/glossary.md": (
        "bf18babc9cd2c8e678040a3fb5591b7256c7074c1069d34f15d2f71bbf5268df"
    ),
    "docs/reference/glossary.md": (
        "e862dd7fdf851222be38685058b5d70274a184959d12a3255fb36bd7a4bd8c14"
    ),
    "docs/toolkit.md": (
        "3ce643624f655ae7684eb320ade6973a8fd17f812d6ba8265ae4bdb2d2826c5e"
    ),
    "docs/stylesheets/toolkit.css": (
        "3f231d0fc3d385f888c2dd44cf00266c37126322bf78d0acef79654d4dce39cf"
    ),
    "overrides/main.html": (
        "32e5ef1b97e59aefbdad89ff7e4901b4aa05773b93b845e17c994e2c3bda19cb"
    ),
    "overrides/404.html": (
        "6151f609299109ac9f7fe059314356da4d3e84369f5f3e0291314687a97ec8a0"
    ),
    "scripts/seo.py": (
        "693443665f04467979718920c8bb25565a40f1d83033c65b7162b73c22f6295d"
    ),
    "tests/test_site.py": (
        "7494215e5b1034373aa6df457574f41659eba191704c542d437afbd307bf426e"
    ),
}
SECTIONS = [
    "Installation",
    "Quickstart",
    "Features",
    "Toolkit",
    "Documentation",
    "Development",
    "Licence",
]
DISCLAIMER = (
    f"{NAME} is an independent project, not affiliated with or endorsed by the "
    "European Banking Authority."
)
FOOTER = (
    "Copyright &copy; 2026 Luuk Hopman. Part of the dpm toolkit: "
    '<a href="https://luukhopman.github.io/dpm-xl/">dpm-xl</a>, '
    '<a href="https://luukhopman.github.io/dpm-xbrl/">dpm-xbrl</a> and '
    '<a href="https://luukhopman.github.io/dpm-synth/">dpm-synth</a>. '
    "Not affiliated with or endorsed by the European Banking Authority."
)


def marked(name: str) -> str:
    """Return the toolkit block with the row of ``name`` marked.

    Returns:
        str: The block as the README and the docs show it.
    """
    row = re.compile(
        rf'^(\| <a href="{re.escape(SITE.format(name))}">.*? \| )(.+) \|$', re.MULTILINE
    )
    text, count = row.subn(r"\1\2 **(this package)** |", CANONICAL)
    assert count == 1, f"no row for {name}"
    return text


def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def docs_home() -> str:
    text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)


def paragraphs(text: str) -> list[str]:
    """Return the text paragraphs, without HTML blocks or headings.

    Returns:
        list[str]: Each paragraph with its whitespace collapsed.
    """
    return [
        " ".join(block.split())
        for block in re.split(r"\n\s*\n", text)
        if block.strip() and not block.lstrip().startswith(("<", "#"))
    ]


def test_canonical_text_is_shared() -> None:
    digest = hashlib.sha256(CANONICAL.encode("utf-8")).hexdigest()
    assert digest == CANONICAL_SHA256, (
        "the toolkit block changed: change it in dpm-xl, dpm-xbrl and dpm-synth "
        "alike, then update CANONICAL_SHA256 in all three"
    )


@pytest.mark.parametrize("path", SHARED_SHA256)
def test_shared_docs_files_are_unchanged(path: str) -> None:
    digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    assert digest == SHARED_SHA256[path], (
        f"{path} changed: change it in dpm-xl, dpm-xbrl and dpm-synth alike, "
        "then update SHARED_SHA256 in all three"
    )


@pytest.mark.parametrize("page", ["index.md", "toolkit.md"])
def test_docs_pages_include_the_toolkit_cards(page: str) -> None:
    text = (ROOT / "docs" / page).read_text(encoding="utf-8")
    assert text.count('--8<-- "docs/.snippets/toolkit-cards.md"') == 1


def test_readme_toolkit_section_is_the_block() -> None:
    section = readme().split("\n## Toolkit\n\n", 1)[1].split("\n## ", 1)[0]
    assert section == marked(NAME)


def test_readme_sections() -> None:
    assert re.findall(r"^## (.+)$", readme(), re.MULTILINE) == SECTIONS


def test_disclaimer_follows_the_pitch() -> None:
    for where, text in (("README.md", readme()), ("docs/index.md", docs_home())):
        assert paragraphs(text)[1] == DISCLAIMER, f"{where}: not under the pitch"


def test_docs_footer_and_navigation() -> None:
    config = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))
    assert config["project"]["copyright"] == FOOTER
    toolkit = next(
        entry["Toolkit"] for entry in config["project"]["nav"] if "Toolkit" in entry
    )
    assert toolkit == [
        {"Overview": "toolkit.md"},
        *({name: SITE.format(name)} for name in PACKAGES if name != NAME),
    ]
