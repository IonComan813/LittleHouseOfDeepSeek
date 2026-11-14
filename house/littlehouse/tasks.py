"""Real-time execution of her actions (M3).

Every action is a generator (see ``actions.process``) that yields *phases* —
walking somewhere, or working at something for a number of seconds — and
returns the text describing what happened. The ``Runner`` plays a script's
steps one after another against the game clock: a step that takes three
minutes really takes three minutes, and the picture (``anim.current_pose``)
draws whatever phase is running at this moment.

Stopping part-way (a new script arrives, free time ends, DSH aborts the turn)
throws ``Interrupted`` into the running step, which decides what a half-done
job means: cleaning keeps its progress, stir-frying burns, fishing catches
nothing.

The runner is advanced by whoever looks at the world (``World.update``): the
house's ticker thread, the HTTP handler waiting for a script, or tests that
fast-forward the clock. It never sleeps itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generator

from . import content as C
from .world import ActionError

Point = tuple[float, float]


@dataclass
class Phase:
    kind: str  # walk | work | wait
    seconds: float
    action: str = ""
    focus: str | None = None
    points: list[Point] = field(default_factory=list)  # walk: the polyline she follows
    label: str = ""  # what she is doing, e.g. "炖萝卜汤"


class Interrupted(Exception):
    """Thrown into a running step when she stops part-way."""

    def __init__(self, done: float) -> None:
        super().__init__("interrupted")
        self.done = done  # seconds already spent in the current phase


Proc = Generator[Phase, None, str]


@dataclass
class StepResult:
    call: str
    ok: bool
    text: str
    start: str = ""  # HH:MM when the step began
    end: str = ""  # HH:MM when it finished
    hint: bool = False  # written without its arguments: the text lists what can go in them


@dataclass
class Report:
    """What became of one submitted script."""

    id: int
    total: int
    started: float
    results: list[StepResult] = field(default_factory=list)
    done: bool = False
    stopped: str = ""  # why it ended before the last step ran, if it did


@dataclass
class Call:
    name: str
    args: list[Any]
    line: int = 0

    def shown(self) -> str:
        return f"{self.name}({', '.join(_fmt_arg(a) for a in self.args)})"


def _fmt_arg(a: Any) -> str:
    if isinstance(a, float) and a.is_integer():
        return str(int(a))
    return str(a)


def length(points: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def along(points: list[Point], d: float) -> tuple[float, float, int]:
    """Point at distance ``d`` along the polyline, and the facing there (1 = right)."""
    facing = 1
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if b[0] != a[0]:
            facing = 1 if b[0] > a[0] else -1
        if d <= seg:
            k = 0 if seg == 0 else d / seg
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, facing
        d -= seg
    end = points[-1]
    return end[0], end[1], facing


def walk(points: list[Point], action: str = "goto") -> Phase:
    return Phase("walk", length(points) / C.WALK_TILES_PER_SEC, action, points=points)


def _hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


class Runner:
    def __init__(self, world) -> None:
        self.w = world
        self.queue: list[Call] = []
        self.gen: Proc | None = None
        self.call: Call | None = None
        self.call_start = 0.0
        self.phase: Phase | None = None
        self.phase_start = 0.0
        self.cursor = 0.0  # game time the runner has played up to
        self.deadline: float | None = None
        self.routine = False  # running the off-hours routine, not her own script
        self.report: Report | None = None
        self.reports: dict[int, Report] = {}
        self._next_id = 1

    # ------------------------------------------------------------------ state

    def busy(self) -> bool:
        return self.gen is not None or bool(self.queue)

    def doing(self) -> str:
        """Short description of the step in progress ('' when idle)."""
        if self.gen is None or self.call is None:
            return ""
        label = self.phase.label if self.phase and self.phase.label else ""
        return label or self.call.shown()

    def next_change(self) -> float | None:
        """Game time at which the current phase ends (None when idle)."""
        if self.gen is None or self.phase is None:
            return None
        return self.phase_start + self.phase.seconds

    # ------------------------------------------------------------------ control

    def submit(self, calls: list[Call], deadline: float | None = None, routine: bool = False) -> int:
        """Start a new script, stopping whatever she was doing."""
        self.interrupt("被新的安排打断了")
        rid = self._next_id
        self._next_id += 1
        now = self.w.clock.timestamp()
        self.report = Report(rid, len(calls), now)
        self.reports[rid] = self.report
        for old in [k for k in self.reports if k <= rid - 8]:
            del self.reports[old]
        self.queue = list(calls)
        self.deadline = deadline
        self.routine = routine
        self.cursor = now
        self.advance()
        return rid

    def interrupt(self, reason: str = "停下了") -> None:
        """Stop the running step (it decides what half-done means) and drop the rest."""
        if self.gen is not None:
            now = self.w.clock.timestamp()
            done = 0.0
            if self.phase is not None:
                done = max(0.0, min(self.phase.seconds, now - self.phase_start))
                if self.phase.kind == "walk" and self.phase.points:
                    x, y, facing = along(self.phase.points, done * C.WALK_TILES_PER_SEC)
                    self.w.stand_near((x, y))
                    self.w.resident["facing"] = facing
            self.cursor = now
            try:
                self.gen.throw(Interrupted(done))
            except StopIteration as e:
                self._finish(True, (e.value or "") or "（做到一半停下了。）")
            except Interrupted:
                self._finish(True, "（做到一半停下了。）")
            except ActionError as e:
                self._finish(False, str(e))
            else:  # a step must not keep going after being interrupted
                self.gen.close()
                self._finish(True, "（做到一半停下了。）")
        if self.report is not None and not self.report.done:
            if self.queue or len(self.report.results) < self.report.total:
                self.report.stopped = self.report.stopped or reason
            self.report.done = True
        self.queue.clear()
        self.routine = False

    def advance(self) -> None:
        """Play the script up to the current game time."""
        now = self.w.clock.timestamp()
        for _ in range(1000):  # instant steps chain; bound it just in case
            if self.gen is not None:
                end = self.phase_start + (self.phase.seconds if self.phase else 0.0)
                if self.phase is not None and end > now:
                    return
                self.cursor = max(self.cursor, end)
                self._resume()
                continue
            if not self.queue:
                if self.report is not None and not self.report.done:
                    self.report.done = True
                return
            self._start(self.queue.pop(0))

    # ------------------------------------------------------------------ internals

    def _start(self, call: Call) -> None:
        from .actions import ACTIONS, ALIASES, INTERNAL, options, process

        w = self.w
        if self.deadline is not None and self.cursor >= self.deadline:
            self.queue.clear()
            if self.report is not None:
                self.report.stopped = "自由活动时间到了"
                self.report.done = True
            return
        self.call, self.call_start = call, self.cursor
        if call.name in INTERNAL and self.routine:
            self.gen = INTERNAL[call.name](w, *call.args)
        else:
            if call.name in ALIASES:
                call = Call(ALIASES[call.name], call.args, call.line)
                self.call = call
            spec = ACTIONS.get(call.name)
            if spec is None:
                self._finish(False, f"没有「{call.name}」这个动作。用 help() 查看可用动作。")
                return
            if len(call.args) < spec.min_args:  # "cook" alone: say what it can be used with
                self._finish(True, options(w, call.name), hint=True)  # no side effects: go on
                return
            if len(call.args) > spec.max_args:
                self._finish(False, f"用法：{spec.signature}")
                return
            self.gen = process(w, call.name, call.args)
        self.phase = None
        self.phase_start = self.cursor
        self._resume()

    def _resume(self) -> None:
        assert self.gen is not None
        prev = self.phase
        try:
            phase = next(self.gen)
        except StopIteration as e:
            self._after_walk(prev)
            self._finish(True, e.value or "")
            return
        except ActionError as e:
            self._finish(False, str(e))
            return
        self._after_walk(prev)
        self.phase = phase
        self.phase_start = self.cursor
        if phase.kind == "walk" and len(phase.points) >= 2:
            # face the way she sets off; the end facing is stored when she arrives
            _, _, facing = along(phase.points, 0.01)
            self.w.resident["facing"] = facing
        if phase.seconds <= 0:
            self.phase.seconds = 0.0

    def _after_walk(self, phase: Phase | None) -> None:
        if phase is not None and phase.kind == "walk" and phase.points:
            _, _, facing = along(phase.points, length(phase.points))
            self.w.resident["facing"] = facing

    def _finish(self, ok: bool, text: str, hint: bool = False) -> None:
        call = self.call
        self.gen = None
        self.phase = None
        self.call = None
        if call is not None and self.report is not None and not self.routine:
            text += self.w.take_kitchen_note()
            self.report.results.append(StepResult(call.shown(), ok, text, _hm(self.call_start), _hm(self.cursor), hint))
        if not ok:
            self.queue.clear()
            if self.report is not None:
                self.report.done = True
