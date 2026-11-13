"""The pseudo-code the agent uses to act in the house.

A script is a sequence of calls separated by ``;`` (or fullwidth ``；``) or newlines::

    goto(厨房); look()
    water(绿萝)
    pick(shell#3)

Arguments are bare words (``厨房``, ``pot#1``), numbers, or quoted strings
(``say("今天天气真好")``). A bare word without parentheses (``look``) is a call
with no arguments. ``//`` starts a comment. Nothing is ever ``eval``'d.

Execution stops at the first failing statement so the agent can re-plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .actions import ACTIONS
from .world import ActionError, World

MAX_STATEMENTS = 20
MAX_SCRIPT_CHARS = 2000
SEPARATORS = ";；\n"
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


class ScriptError(Exception):
    pass


@dataclass
class Call:
    name: str
    args: list[str | float]
    line: int


def _is_word_char(c: str) -> bool:
    return c.isalnum() or c in "_#-." or "一" <= c <= "鿿"


def parse(src: str) -> list[Call]:
    if len(src) > MAX_SCRIPT_CHARS:
        raise ScriptError(f"脚本太长了（上限 {MAX_SCRIPT_CHARS} 字符）。")
    calls: list[Call] = []
    i, n, line = 0, len(src), 1

    def skip_ws() -> None:
        nonlocal i, line
        while i < n:
            c = src[i]
            if c == "\n":
                line += 1
                i += 1
            elif c in " \t\r":
                i += 1
            elif src.startswith("//", i):
                while i < n and src[i] != "\n":
                    i += 1
            else:
                break

    def read_word() -> str:
        nonlocal i
        start = i
        while i < n and _is_word_char(src[i]):
            i += 1
        return src[start:i]

    def read_string() -> str:
        nonlocal i
        quote = src[i]
        closing = {"「": "」", "“": "”"}.get(quote, quote)
        i += 1
        out = []
        while i < n and src[i] != closing:
            if src[i] == "\\" and i + 1 < n:
                i += 1
            out.append(src[i])
            i += 1
        if i >= n:
            raise ScriptError(f"第 {line} 行：字符串没有闭合。")
        i += 1
        return "".join(out)

    while True:
        skip_ws()
        while i < n and src[i] in SEPARATORS:
            i += 1
            skip_ws()
        if i >= n:
            break
        start_line = line
        name = read_word()
        if not name:
            raise ScriptError(f"第 {line} 行：看不懂「{src[i:i + 10]}」，应该是 动作(参数) 的形式。")
        skip_ws()
        args: list[str | float] = []
        if i < n and src[i] in "(（":
            close = ")" if src[i] == "(" else "）"
            i += 1
            skip_ws()
            while i < n and src[i] not in (")", "）"):
                if src[i] in "\"'「“":
                    args.append(read_string())
                else:
                    w = read_word()
                    if not w:
                        raise ScriptError(f"第 {line} 行：参数里有看不懂的字符「{src[i]}」。")
                    args.append(float(w) if _NUMBER.fullmatch(w) else w)
                skip_ws()
                if i < n and src[i] in ",，":
                    i += 1
                    skip_ws()
            if i >= n:
                raise ScriptError(f"第 {start_line} 行：缺少右括号 {close}。")
            i += 1
        calls.append(Call(name, args, start_line))
        if len(calls) > MAX_STATEMENTS:
            raise ScriptError(f"一次最多 {MAX_STATEMENTS} 个动作。")
        skip_ws()
        if i < n and src[i] not in SEPARATORS and not _is_word_char(src[i]):
            raise ScriptError(f"第 {line} 行：动作之间请用分号或换行隔开。")
    return calls


@dataclass
class StepResult:
    call: str
    ok: bool
    text: str


def run(world: World, src: str) -> list[StepResult]:
    """Parse and execute a script. Raises ScriptError for syntax problems."""
    calls = parse(src)
    if not calls:
        raise ScriptError("脚本是空的。试试 look()。")
    results: list[StepResult] = []
    world.tick()
    for c in calls:
        shown = f"{c.name}({', '.join(str(a) for a in c.args)})"
        spec = ACTIONS.get(c.name)
        if spec is None:
            results.append(StepResult(shown, False, f"没有「{c.name}」这个动作。用 help() 查看可用动作。"))
            break
        if not (spec.min_args <= len(c.args) <= spec.max_args):
            results.append(StepResult(shown, False, f"用法：{spec.signature}"))
            break
        try:
            text = spec.fn(world, *c.args)
        except ActionError as e:
            results.append(StepResult(shown, False, str(e)))
            break
        results.append(StepResult(shown, True, text))
    return results


def format_results(results: list[StepResult]) -> str:
    lines = []
    for r in results:
        mark = "✓" if r.ok else "✗"
        lines.append(f"{mark} {r.call}\n  {r.text.replace(chr(10), chr(10) + '  ')}")
    return "\n".join(lines)
