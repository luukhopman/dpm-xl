"""Check what the documentation site gives search engines.

dpm-xl, dpm-xbrl and dpm-synth carry this file unchanged. It checks:

* every docs page has a description, used as its meta description, and no
  two pages share one;
* the site uses the templates in ``overrides/`` (social tags, home page
  title, 404 page) and ships the social preview image they name;
* ``scripts/seo.py``, which adds sitemap dates, ``robots.txt`` and the home
  page's JSON-LD block after the build.
"""

from __future__ import annotations

import json
import re
import struct
import tomllib
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
CONFIG = tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]
FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
SITE_URL = "https://example.org/pkg/"

spec = spec_from_file_location("seo", ROOT / "scripts" / "seo.py")
assert spec is not None and spec.loader is not None
seo = module_from_spec(spec)
spec.loader.exec_module(seo)


def description(page: Path) -> str:
    match = FRONT_MATTER.match(page.read_text(encoding="utf-8"))
    if not match:
        return ""
    for line in match["body"].splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "description":
            return value.strip().strip('"')
    return ""


def test_every_page_has_a_unique_description() -> None:
    pages = sorted(
        path.relative_to(DOCS).as_posix()
        for path in DOCS.rglob("*.md")
        if ".snippets" not in path.parts
    )
    descriptions = {page: description(DOCS / page) for page in pages}
    missing = [page for page, text in descriptions.items() if not text]
    assert not missing, f"pages without a description: {missing}"
    counts = Counter(descriptions.values())
    shared = [page for page, text in descriptions.items() if counts[text] > 1]
    assert not shared, f"pages sharing a description: {shared}"


def test_site_uses_the_overrides() -> None:
    assert CONFIG["theme"]["custom_dir"] == "overrides"
    for template in ("main.html", "404.html"):
        assert (ROOT / "overrides" / template).is_file()
    image = (DOCS / "assets" / "social-preview.png").read_bytes()
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", image[16:24]) == (1280, 640)


def test_source_page() -> None:
    assert seo.source_page(DOCS, SITE_URL, SITE_URL) == DOCS / "index.md"
    assert (
        seo.source_page(DOCS, SITE_URL, f"{SITE_URL}getting-started/")
        == DOCS / "getting-started.md"
    )
    assert seo.source_page(DOCS, SITE_URL, f"{SITE_URL}no-such-page/") is None


def test_add_lastmod() -> None:
    sitemap = (
        "<urlset>\n  <url>\n    <loc>https://example.org/pkg/</loc>\n"
        "    <lastmod>2000-01-01</lastmod>\n  </url>\n"
        "  <url>\n    <loc>https://example.org/pkg/a/</loc>\n  </url>\n</urlset>\n"
    )
    assert seo.add_lastmod(sitemap, {SITE_URL: "2026-01-02"}) == (
        "<urlset>\n  <url>\n    <loc>https://example.org/pkg/</loc>\n"
        "    <lastmod>2026-01-02</lastmod>\n  </url>\n"
        "  <url>\n    <loc>https://example.org/pkg/a/</loc>\n  </url>\n</urlset>\n"
    )


def test_last_changed_is_a_date() -> None:
    for page in (DOCS / "index.md", None):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", seo.last_changed(page, ROOT))


def test_robots_names_the_sitemap() -> None:
    assert seo.robots(SITE_URL) == (
        "User-agent: *\nAllow: /\n\nSitemap: https://example.org/pkg/sitemap.xml\n"
    )


def test_json_ld() -> None:
    block = seo.json_ld(PROJECT, CONFIG["repo_url"], CONFIG["site_url"])
    data = json.loads(block.split(">", 1)[1].rsplit("<", 1)[0])
    assert data == {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": PROJECT["name"],
        "description": PROJECT["description"],
        "codeRepository": CONFIG["repo_url"],
        "url": CONFIG["site_url"],
        "programmingLanguage": "Python",
        "license": "https://spdx.org/licenses/MIT.html",
        "version": PROJECT["version"],
    }
    page = "<html><head><title>t</title></head><body></body></html>"
    once = seo.add_json_ld(page, block)
    assert seo.add_json_ld(once, block) == once
    assert once.count("application/ld+json") == 1
    assert once.index("application/ld+json") < once.index("</head>")


def test_descriptions_match() -> None:
    assert CONFIG["site_description"] == PROJECT["description"]
