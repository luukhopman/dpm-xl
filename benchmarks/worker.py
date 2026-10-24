"""Benchmark worker, run by ``run.py`` inside each tool's own environment.

Usage: ``python -I worker.py TOOL TASK [FILE]`` with TOOL one of ``dpm-xl``,
``pydpm-xl`` or ``dpmcore`` and TASK one of:

* ``import``: import the tool's syntax API and exit (timed from outside);
* ``corpus FILE``: syntax-check every line of FILE, print a JSON summary with
  the time spent in the checking loop only;
* ``messages FILE``: syntax-check every expression of FILE (``#`` lines are
  comments; ``label<TAB>expression`` lines keep their label) and print the
  verdict and error message of each as JSON.

This file uses the standard library only, so it runs in any environment.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from collections.abc import Callable

Checker = Callable[[str], "tuple[bool, str | None]"]


def dpm_xl() -> Checker:
    """Return a checker using dpm-xl, as ``dpm-xl check`` does.

    Returns:
        Checker: Expression to (valid, message).
    """
    from dpmxl import DpmXlSyntaxError, parse_program

    def check(expression: str) -> tuple[bool, str | None]:
        try:
            parse_program(expression)
        except DpmXlSyntaxError as error:
            return False, str(error)
        return True, None

    return check


def pydpm_xl() -> Checker:
    """Return a checker using pydpm-xl's syntax API.

    Returns:
        Checker: Expression to (valid, message).
    """
    from py_dpm.api import SyntaxAPI

    api = SyntaxAPI()

    def check(expression: str) -> tuple[bool, str | None]:
        try:
            result = api.validate_expression(expression)
        except Exception as error:
            return False, f"{type(error).__name__}: {error}"
        return bool(result.is_valid), result.error_message

    return check


def dpmcore() -> Checker:
    """Return a checker using dpmcore's syntax service.

    Returns:
        Checker: Expression to (valid, message).
    """
    from dpmcore.services.syntax import SyntaxService

    service = SyntaxService()

    def check(expression: str) -> tuple[bool, str | None]:
        try:
            result = service.validate(expression)
        except Exception as error:
            return False, f"{type(error).__name__}: {error}"
        return bool(result.is_valid), result.error_message

    return check


TOOLS = {"dpm-xl": dpm_xl, "pydpm-xl": pydpm_xl, "dpmcore": dpmcore}


def main(argv: list[str]) -> int:
    """Run one task.

    Returns:
        int: The exit status.
    """
    tool, task = argv[0], argv[1]
    check = TOOLS[tool]()
    if task == "import":
        return 0
    with pathlib.Path(argv[2]).open(encoding="utf-8") as file:
        lines = [line for line in file.read().splitlines() if line.strip()]
    if task == "corpus":
        start = time.perf_counter()
        rejected = [line for line in lines if not check(line)[0]]
        seconds = time.perf_counter() - start
        print(
            json.dumps(
                {
                    "expressions": len(lines),
                    "accepted": len(lines) - len(rejected),
                    "loop_seconds": seconds,
                    "rejected": rejected,
                }
            )
        )
        return 0
    results = []
    for line in lines:
        if line.startswith("#"):
            continue
        label, _, expression = line.rpartition("\t")
        valid, message = check(expression)
        results.append(
            {
                "label": label or None,
                "expression": expression,
                "valid": valid,
                "message": message,
            }
        )
    print(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
