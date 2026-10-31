"""Finish a built documentation site for search engines.

The same file in dpm-xl, dpm-xbrl and dpm-synth; ``tests/test_toolkit.py``
pins its hash. ``scripts/build_docs.py`` calls :func:`finish` after the
Zensical build. It:

* adds a ``<lastmod>`` to every URL of ``sitemap.xml``: the date of the last
  commit that changed the page's source, or today for a page git does not
  know;
* writes ``robots.txt``, which allows everything and names the sitemap;
* adds one JSON-LD ``SoftwareSourceCode`` block to the home page, from the
  name, description, version and licence in ``pyproject.toml``.

The Open Graph and Twitter tags, the home page title and the 404 page come
from the templates in ``overrides/``.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path

LOC = re.compile(r"(?P<indent>[ \t]*)<loc>(?P<url>[^<]+)</loc>")
JSON_LD = '<script type="application/ld+json">{}</script>'


def source_page(docs: Path, site_url: str, url: str) -> Path | None:
    """Return the Markdown source of a site URL, if there is one.

    Returns:
        Path | None: ``docs/<path>/index.md`` or ``docs/<path>.md``.
    """
    path = url.removeprefix(site_url).strip("/")
    candidates = [docs / path / "index.md"]
    if path:
        candidates.append(docs / f"{path}.md")
    return next((page for page in candidates if page.is_file()), None)


def last_changed(path: Path | None, root: Path) -> str:
    """Return the date of the last commit that changed ``path``.

    Returns:
        str: An ISO date; today without git or a commit for the file.
    """
    git = shutil.which("git")
    if path is not None and git is not None:
        log = subprocess.run(
            [git, "log", "-1", "--format=%cs", "--", str(path)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if log.returncode == 0 and log.stdout.strip():
            return log.stdout.strip()
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def add_lastmod(sitemap: str, dates: dict[str, str]) -> str:
    """Add a ``<lastmod>`` after every ``<loc>`` that has a date.

    Returns:
        str: The sitemap, with any earlier ``<lastmod>`` replaced.
    """
    sitemap = re.sub(r"\s*<lastmod>[^<]*</lastmod>", "", sitemap)

    def lastmod(match: re.Match[str]) -> str:
        date = dates.get(match["url"])
        if date is None:
            return match[0]
        return f"{match[0]}\n{match['indent']}<lastmod>{date}</lastmod>"

    return LOC.sub(lastmod, sitemap)


def robots(site_url: str) -> str:
    """Return a ``robots.txt`` that allows everything and names the sitemap.

    Returns:
        str: The file content.
    """
    return f"User-agent: *\nAllow: /\n\nSitemap: {site_url}sitemap.xml\n"


def json_ld(project: dict[str, object], repo_url: str, site_url: str) -> str:
    """Return the home page's JSON-LD block for the package.

    Returns:
        str: A ``<script type="application/ld+json">`` element.
    """
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareSourceCode",
        "name": project["name"],
        "description": project["description"],
        "codeRepository": repo_url,
        "url": site_url,
        "programmingLanguage": "Python",
        "license": f"https://spdx.org/licenses/{project['license']}.html",
        "version": project["version"],
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return JSON_LD.format(text.replace("</", "<\\/"))


def add_json_ld(page: str, block: str) -> str:
    """Put ``block`` at the end of the page's ``<head>``, replacing an earlier one.

    Returns:
        str: The page.
    """
    page = re.sub(r'<script type="application/ld\+json">.*?</script>\n?', "", page)
    return page.replace("</head>", f"{block}\n</head>", 1)


def finish(
    root: Path, site: Path, config: dict[str, object], project: dict[str, object]
) -> None:
    """Add lastmod dates, robots.txt and the JSON-LD block to a built site.

    Args:
        root: The repository root.
        site: The built site.
        config: The ``[project]`` table of ``zensical.toml``.
        project: The ``[project]`` table of ``pyproject.toml``.
    """
    site_url = str(config["site_url"])
    docs = root / str(config.get("docs_dir", "docs"))
    sitemap_path = site / "sitemap.xml"
    sitemap = sitemap_path.read_text(encoding="utf-8")
    dates = {
        match["url"]: last_changed(source_page(docs, site_url, match["url"]), root)
        for match in LOC.finditer(sitemap)
    }
    sitemap_path.write_text(add_lastmod(sitemap, dates), encoding="utf-8")
    (site / "robots.txt").write_text(robots(site_url), encoding="utf-8")
    home = site / "index.html"
    block = json_ld(project, str(config["repo_url"]), site_url)
    home.write_text(
        add_json_ld(home.read_text(encoding="utf-8"), block), encoding="utf-8"
    )
