"""The pseudo-code the agent uses to act in the house.

A script is a sequence of calls separated by ``;`` (or fullwidth ``；``) or newlines::

    goto(厨房); look()
    water(绿萝)
    pick(shell#3)

Arguments are bare words (``厨房``, ``pot#1``), numbers, or quoted strings
(``say("今天天气真好")``). A bare word without parentheses (``look``) is a call
with no arguments. ``//`` starts a comment. Nothing is ever ``eval``'d.

Execution stops at the first failing statement so the agent can re-plan.
Since M3 the steps take real time: ``World.runner`` (tasks.py) plays them
against the game clock. ``run()`` here fast-forwards the clock instead — for
tests and for trying things out offline.
"""

from __future__ import annotations

import re
from datetime import datetime

from .tasks import Call, Report, StepResult
from .world import World

MAX_STATEMENTS = 20
MAX_SCRIPT_CHARS = 2000
SEPARATORS = ";；\n"
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


class ScriptError(Exception):
    pass


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


def run(world: World, src: str, deadline: float | None = None) -> list[StepResult]:
    """Parse a script and play it to the end by fast-forwarding the game clock.

    Raises ScriptError for syntax problems. (The house server plays scripts in
    real time instead: see ``server.House.do``.)
    """
    calls = parse(src)
    if not calls:
        raise ScriptError("脚本是空的。试试 look()。")
    world.update()
    rid = world.runner.submit(calls, deadline)
    report = world.runner.reports[rid]
    while not report.done:
        nxt = world.runner.next_change()
        if nxt is None:
            world.runner.advance()
            if not world.runner.busy():
                break
            continue
        world.clock.advance(max(0.0, nxt - world.clock.timestamp()) + 0.001)
        world.update()
    return report.results


def format_results(results: list[StepResult]) -> str:
    lines = []
    for r in results:
        mark = "？" if r.hint else "✓" if r.ok else "✗"
        when = f"  [{r.start}]" if r.start and r.start == r.end else f"  [{r.start}–{r.end}]" if r.start else ""
        lines.append(f"{mark} {r.call}{when}\n  {r.text.replace(chr(10), chr(10) + '  ')}")
    return "\n".join(lines)


def format_report(world: World, report: Report) -> str:
    """The text the agent gets back for a script: steps, what happened meanwhile, the time."""
    lines = [format_results(report.results)] if report.results else []
    started = datetime.fromtimestamp(report.started).isoformat(timespec="seconds")
    news = [e.text for e in world.events if e.actor == "world" and e.t >= started]
    if news:
        lines.append("期间：" + "；".join(dict.fromkeys(news)) + "。")
    if not report.done:
        left = report.total - len(report.results) - 1
        more = f"，后面还有 {left} 步会接着做" if left > 0 else ""
        lines.append(f"（还在进行：{world.runner.doing()}{more}。可以先做别的打算，用 look() 看看进度。）")
    elif report.stopped:
        lines.append(f"（{report.stopped}，后面的步骤没有执行。）")
    if report.done:
        from .actions import menu_line

        lines.append(menu_line(world))
    tail = world.free_time_text() or f"现在 {world.now():%H:%M}"
    if not (report.results and report.results[-1].text.endswith(tail)):  # look() already says it
        lines.append(tail)
    return "\n".join(lines)
