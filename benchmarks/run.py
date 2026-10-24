r"""Run the benchmarks and write ``results.md`` and ``results.json``.

Usage (see README.md for setting up the environments)::

    python benchmarks/run.py --corpus corpus.txt \\
        --env dpm-xl=envs/dpm-xl --env pydpm-xl=envs/pydpm-xl \\
        --env dpmcore=envs/dpmcore

Each ``--env`` names a virtual environment with one tool installed. Every
measurement runs ``python -I benchmarks/worker.py`` in that environment as a
separate process: one warm-up run, then the best wall-clock time of
``--runs`` runs (3 by default), with the peak resident memory (RSS) of those
runs. Linux only (it reads ``/proc/cpuinfo`` and uses ``os.wait4``).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKER = HERE / "worker.py"
CONSTRUCTS = HERE / "inputs" / "constructs.txt"
MALFORMED = HERE / "inputs" / "malformed.txt"
DISTRIBUTIONS = {"dpm-xl": "dpm-xl", "pydpm-xl": "pydpm_xl", "dpmcore": "dpmcore"}


def timed(command: list[str], runs: int) -> dict[str, object]:
    """Run a command once to warm up, then ``runs`` times.

    Returns:
        dict[str, object]: Best wall seconds, peak RSS in MB and the last
        run's standard output.
    """
    walls: list[float] = []
    peak = 0
    output = ""
    for attempt in range(runs + 1):
        start = time.perf_counter()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
        assert process.stdout is not None
        output = process.stdout.read()
        _, status, usage = os.wait4(process.pid, 0)
        wall = time.perf_counter() - start
        process.returncode = os.waitstatus_to_exitcode(status)
        if process.returncode:
            raise SystemExit(f"{command} exited with {process.returncode}")
        if attempt:
            walls.append(wall)
            peak = max(peak, usage.ru_maxrss // 1024)
    return {"seconds": min(walls), "rss_mb": peak, "runs": walls, "output": output}


def environment_facts(python: str, tool: str) -> dict[str, object]:
    """Read the tool version, Python version and installed footprint.

    Returns:
        dict[str, object]: Version, Python, distribution count and size.
    """
    script = (
        "import importlib.metadata as m, json, platform, sysconfig, pathlib\n"
        f"dist = m.distribution({DISTRIBUTIONS[tool]!r})\n"
        "site = pathlib.Path(sysconfig.get_paths()['purelib'])\n"
        "size = sum(p.stat().st_size for p in site.rglob('*') if p.is_file())\n"
        "names = sorted({d.metadata['Name'].lower() for d in m.distributions()}"
        " - {'pip', 'setuptools', 'wheel'})\n"
        "print(json.dumps({'version': dist.version,"
        " 'python': platform.python_version(),"
        " 'distributions': len(names), 'site_packages_mb': size / 2**20}))\n"
    )
    result = subprocess.run(
        [python, "-I", "-c", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def cpu_model() -> str:
    """Return the CPU model name.

    Returns:
        str: The model, or the machine type when unknown.
    """
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.machine()


def measure(tool: str, python: str, corpus: Path, runs: int) -> dict[str, object]:
    """Run every measurement for one tool.

    Returns:
        dict[str, object]: The tool's results.
    """
    worker = [python, "-I", str(WORKER), tool]
    print(f"{tool}: import", file=sys.stderr)
    imported = timed([*worker, "import"], runs)
    print(f"{tool}: corpus", file=sys.stderr)
    checked = timed([*worker, "corpus", str(corpus)], runs)
    summary = json.loads(str(checked["output"]))
    print(f"{tool}: constructs and messages", file=sys.stderr)
    constructs = json.loads(
        subprocess.run(
            [*worker, "messages", str(CONSTRUCTS)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    malformed = json.loads(
        subprocess.run(
            [*worker, "messages", str(MALFORMED)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    return {
        **environment_facts(python, tool),
        "import_seconds": imported["seconds"],
        "import_rss_mb": imported["rss_mb"],
        "corpus_seconds": checked["seconds"],
        "corpus_rss_mb": checked["rss_mb"],
        "expressions": summary["expressions"],
        "accepted": summary["accepted"],
        "rejected": summary["rejected"],
        "constructs": constructs,
        "malformed": malformed,
    }


def _short(text: str | None, limit: int = 110) -> str:
    if text is None:
        return "accepted"
    flat = " ".join(text.split()).replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def markdown(results: dict[str, object]) -> str:
    """Render the results as the Markdown the docs page includes.

    Returns:
        str: Tables for speed, footprint, coverage, constructs and messages.
    """
    tools: dict[str, dict] = results["tools"]  # type: ignore[assignment]
    names = list(tools)
    header = "| | " + " | ".join(f"{name} {tools[name]['version']}" for name in names)
    rule = "| --- |" + " --- |" * len(names)

    def row(label: str, cell) -> str:
        return f"| {label} | " + " | ".join(cell(tools[name]) for name in names) + " |"

    lines = [
        f"Measured on {results['date']} on {results['machine']}, "
        f"{results['os']}; Python "
        + ", ".join(sorted({str(tool["python"]) for tool in tools.values()}))
        + f". Best of {results['runs']} warm runs; peak RSS over those runs.",
        "",
        "#### Speed and footprint",
        "",
        header + " |",
        rule,
        row(
            "Syntax check of the corpus (whole process)",
            lambda t: f"{t['corpus_seconds']:.2f} s, {t['corpus_rss_mb']} MB",
        ),
        row(
            "Per expression",
            lambda t: f"{t['corpus_seconds'] / t['expressions'] * 1e6:,.0f} µs",
        ),
        row(
            "`import` (whole process)",
            lambda t: f"{t['import_seconds']:.2f} s, {t['import_rss_mb']} MB",
        ),
        row(
            "Installed environment",
            lambda t: (
                f"{t['distributions']} distributions, {t['site_packages_mb']:.0f} MB"
            ),
        ),
        "",
        "#### Coverage of the EBA corpus",
        "",
        header + " |",
        rule,
        row(
            "Expressions accepted",
            lambda t: f"{t['accepted']:,} of {t['expressions']:,}",
        ),
        row(
            "Rejected",
            lambda t: (
                "<br>".join(f"`{_short(line, 60)}`" for line in t["rejected"]) or "none"
            ),
        ),
        "",
        "#### DPM-XL constructs beyond the EBA rules",
        "",
        header + " |",
        rule,
    ]
    for index, construct in enumerate(tools[names[0]]["constructs"]):
        lines.append(
            f"| {construct['label']}: `{construct['expression']}` | "
            + " | ".join(
                "accepted" if tools[name]["constructs"][index]["valid"] else "rejected"
                for name in names
            )
            + " |"
        )
    lines += ["", "#### Syntax error messages", ""]
    for index, case in enumerate(tools[names[0]]["malformed"]):
        lines += [f"`{case['expression']}`", ""]
        for name in names:
            message = tools[name]["malformed"][index]["message"]
            lines.append(f"- {name}: {_short(message, 200)}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Parse the arguments, measure every tool and write the results.

    Returns:
        int: The exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--env",
        action="append",
        required=True,
        metavar="TOOL=VENV",
        help="a tool (dpm-xl, pydpm-xl, dpmcore) and its virtual environment",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", type=Path, default=HERE)
    arguments = parser.parse_args()
    tools = {}
    for entry in arguments.env:
        tool, _, venv = entry.partition("=")
        if tool not in DISTRIBUTIONS:
            parser.error(f"unknown tool {tool}")
        python = str(Path(venv) / "bin" / "python")
        tools[tool] = measure(tool, python, arguments.corpus, arguments.runs)
    results = {
        "date": datetime.date.today().isoformat(),
        "machine": f"{cpu_model()}, {os.cpu_count()} cores",
        "os": f"{platform.system()} {platform.release()}",
        "runs": arguments.runs,
        "tools": tools,
    }
    arguments.out.mkdir(parents=True, exist_ok=True)
    (arguments.out / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (arguments.out / "results.md").write_text(
        markdown(results) + "\n", encoding="utf-8"
    )
    print(f"wrote {arguments.out / 'results.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
