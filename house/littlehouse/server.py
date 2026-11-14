"""Local control server for the house.

Listens on 127.0.0.1 only. Every request except ``/health`` must carry the
token from the discovery file (``<state>/house.json``) in ``X-House-Token``.
The DSH plugin reads that file to find the port and token.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from . import __version__
from .actions import help_text
from .display import Display, pygame_available
from . import content as C
from .script import ScriptError, format_report, parse, refuse_bad_steps
from .world import Event, World

MAX_BODY = 16 * 1024
DEFAULT_WAIT = 15 * 60  # longest a /do request waits for its script (seconds); the script itself carries on
# What she may do outside her free time (in reply to a message, say): look, nothing else.
LOOK_ONLY = ("surroundings", "inventory", "help")


class RenderUnavailable(Exception):
    pass
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


class House:
    """World + persistence + a lock, shared by the HTTP threads and the ticker."""

    def __init__(self, state_dir: Path, world: World | None = None) -> None:
        self.state_dir = state_dir
        self.world = world or World()
        self.lock = threading.RLock()
        self.save_path = state_dir / "world.json"
        self.events_path = state_dir / "events.jsonl"
        state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.world.load(self.save_path)
            self.world.events = self._recent_events()
            self.world.event_sink = self._append_event
            self.world.update()

    def _recent_events(self, limit: int = 300) -> list[Event]:
        """Reload the tail of the event log so news survives a restart."""
        if not self.events_path.exists():
            return []
        out = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(Event(**json.loads(line)))
            except (ValueError, TypeError):
                continue
        return out

    def _append_event(self, ev: Event) -> None:
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")

    def save(self) -> None:
        with self.lock:
            self.world.save(self.save_path)

    def screenshot(self, scale: int = 2) -> bytes:
        """One still frame as PNG (needs pygame-ce; no window, no loop)."""
        try:
            from . import render
        except ImportError as e:
            raise RenderUnavailable("画面需要 pygame-ce：pip install pygame-ce") from e
        with self.lock:
            self.world.update()
            png = render.render_png(self.world, scale)
        try:
            (self.state_dir / "latest.png").write_bytes(png)
        except OSError:
            pass
        return png

    def tick(self) -> None:
        with self.lock:
            self.world.update()

    def do(self, src: str, wait: float = DEFAULT_WAIT, look_only: bool = False) -> dict[str, Any]:
        """Start a script in real time and wait (at most ``wait`` real seconds)
        for it to finish; the script keeps going after that and ``report(id)``
        picks it up again. Raises ScriptError.

        ``look_only`` (outside her free time): only looking (``LOOK_ONLY``) is
        allowed; it is answered at once and does not disturb her everyday routine."""
        calls = parse(src)
        if not calls:
            raise ScriptError("脚本是空的。试试 surroundings()。")
        if look_only:
            return self.look_only(calls)
        w = self.world
        with self.lock:
            w.update()
            refuse_bad_steps(calls, w)
            free_until = w.resident.get("free_until", 0.0)
            deadline = free_until if free_until > w.clock.timestamp() else None
            rid = w.runner.submit(calls, deadline)
        return self.report(rid, wait)

    def look_only(self, calls) -> dict[str, Any]:
        from .actions import ACTIONS

        bad = [c.name for c in calls if c.name not in LOOK_ONLY]
        if bad:
            raise ScriptError("现在不是自由活动时间，你在过自己的日常：只能看看（" + "、".join(f"{n}()" for n in LOOK_ONLY)
                              + "），不能做「" + "、".join(dict.fromkeys(bad)) + "」。想做的事等下次自由活动。")
        with self.lock:
            w = self.world
            w.update()
            lines = [f"✓ {c.shown()}\n  " + str(ACTIONS[c.name].fn(w)).replace("\n", "\n  ") for c in calls]
        return {"ok": True, "done": True, "id": 0, "text": "\n".join(lines), "results": []}

    def report(self, rid: int, wait: float = 0.0) -> dict[str, Any]:
        """What became of script ``rid``, waiting up to ``wait`` real seconds for it to finish."""
        w = self.world
        with self.lock:
            report = w.runner.reports.get(rid)
        if report is None:
            return {"ok": False, "done": True, "id": rid, "text": "（找不到这段安排了。）", "results": []}
        limit = time.monotonic() + max(0.0, wait)
        while not report.done and time.monotonic() < limit:
            time.sleep(0.2)
            with self.lock:
                w.update()
        with self.lock:
            w.update()
            w.save(self.save_path)
            return {
                "ok": all(r.ok for r in report.results) and not report.stopped,
                "done": report.done,
                "id": rid,
                "text": format_report(w, report),
                "results": [asdict(r) for r in report.results],
            }

    def status(self) -> dict[str, Any]:
        with self.lock:
            w = self.world
            w.update()
            idle = w.current_idle()
            return {
                "now": w.clock.timestamp(),  # the game clock: the one time everybody tells her
                "free": w.free(),
                "free_until": w.resident.get("free_until", 0.0),
                "busy": w.runner.busy() and not w.runner.routine,
                "doing": w.runner.doing() if not w.runner.routine else "",
                "idle": idle.text if idle else w.resident.get("idle", ""),
                "location": w.location,
                "location_name": C.ROOMS[w.location].name,
            }


def make_handler(house: House, token: str, on_shutdown=None, display: Display | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LittleHouse/" + __version__

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
            if os.environ.get("LH_HOUSE_VERBOSE"):
                super().log_message(fmt, *args)

        # ---------------------------------------------------------- helpers

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self, auth: bool = True) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ALLOWED_HOSTS:
                self._send(403, {"ok": False, "error": "bad host"})
                return False
            if auth and not hmac.compare_digest(self.headers.get("X-House-Token", ""), token):
                self._send(401, {"ok": False, "error": "bad token"})
                return False
            return True

        def _body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(413, {"ok": False, "error": "body too large"})
                return None
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self._send(415, {"ok": False, "error": "expected application/json"})
                return None
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"ok": False, "error": "invalid json"})
                return None
            if not isinstance(data, dict):
                self._send(400, {"ok": False, "error": "expected an object"})
                return None
            return data

        # ---------------------------------------------------------- routes

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                if self._guard(auth=False):
                    self._send(200, {"ok": True, "version": __version__, "pid": os.getpid()})
                return
            if not self._guard():
                return
            if path == "/look":
                with house.lock:
                    house.world.update()
                    text = house.world.look()
                self._send(200, {"ok": True, "text": text})
            elif path == "/status":
                self._send(200, {"ok": True, **house.status()})
            elif path == "/help":
                self._send(200, {"ok": True, "text": help_text()})
            elif path == "/window":
                self._send(200, {"ok": True, "open": bool(display and display.is_open)})
            elif path == "/state":
                with house.lock:
                    house.world.update()
                    state = house.world.to_json()
                self._send(200, {"ok": True, "state": state})
            elif path == "/screenshot":
                query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                scale = 2 if (query.get("scale") or ["2"])[0] == "2" else 1
                try:
                    png = house.screenshot(scale)
                except RenderUnavailable as e:
                    self._send(501, {"ok": False, "error": str(e)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(png)
            elif path == "/news":
                query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                since = (query.get("since") or [""])[0]
                with house.lock:
                    house.world.update()
                    news = [asdict(e) for e in house.world.news_since(since)][-20:]
                self._send(200, {"ok": True, "news": news})
            elif path == "/events":
                query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                since = (query.get("since") or [""])[0]
                actor = (query.get("actor") or [""])[0]
                with house.lock:
                    events = [asdict(e) for e in house.world.events
                              if e.t > since and (not actor or e.actor == actor)][-50:]
                self._send(200, {"ok": True, "events": events})
            else:
                self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if not self._guard():
                return
            if path == "/window":
                body = self._body()
                if body is None:
                    return
                if display is None or not pygame_available():
                    self._send(501, {"ok": False, "error": "画面需要 pygame-ce：pip install pygame-ce"})
                    return
                display.request(bool(body.get("open", True)), body.get("scale"))
                self._send(200, {"ok": True, "open": display.want_open})
                return
            if path == "/session":
                body = self._body()
                if body is None:
                    return
                try:
                    until = float(body.get("free_until") or 0)
                except (TypeError, ValueError):
                    self._send(400, {"ok": False, "error": "free_until must be a number"})
                    return
                with house.lock:
                    house.world.update()
                    before = house.world.set_free(until)
                    house.world.update()
                    house.world.save(house.save_path)
                self._send(200, {"ok": True, "before": before, **house.status()})
                return
            if path == "/report":
                body = self._body()
                if body is None:
                    return
                try:
                    rid, wait = int(body.get("id", 0)), float(body.get("wait", 0))
                except (TypeError, ValueError):
                    self._send(400, {"ok": False, "error": "id and wait must be numbers"})
                    return
                self._send(200, house.report(rid, max(0.0, min(wait, 3600.0))))
                return
            if path == "/interrupt":
                with house.lock:
                    if house.world.runner.busy() and not house.world.runner.routine:
                        house.world.runner.interrupt("停下了")
                    house.world.update()
                self._send(200, {"ok": True, **house.status()})
                return
            if path == "/shutdown":
                house.save()
                self._send(200, {"ok": True})
                if on_shutdown is not None:
                    threading.Thread(target=on_shutdown, daemon=True).start()
                return
            if path != "/do":
                self._send(404, {"ok": False, "error": "not found"})
                return
            body = self._body()
            if body is None:
                return
            script = body.get("script")
            if not isinstance(script, str):
                self._send(400, {"ok": False, "error": "script must be a string"})
                return
            try:
                wait = float(body.get("wait", DEFAULT_WAIT))
            except (TypeError, ValueError):
                wait = DEFAULT_WAIT
            try:
                out = house.do(script, max(0.0, min(wait, 3600.0)), look_only=bool(body.get("look_only")))
            except ScriptError as e:
                self._send(200, {"ok": False, "done": True, "text": f"✗ 脚本错误：{e}", "results": []})
                return
            self._send(200, out)

    return Handler


def serve(state_dir: Path, port: int = 8770, tick_seconds: float = 30.0, window: bool = False, scale: int = 2) -> None:
    """Run the house. The HTTP server lives on a thread; the main thread hosts
    the (optional) live window, which only draws while it is open."""
    house = House(state_dir)
    token = os.environ.get("LH_HOUSE_TOKEN") or secrets.token_urlsafe(24)
    stop = threading.Event()
    display = Display(house, scale)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(house, token, stop.set, display))
    actual_port = httpd.server_address[1]
    discovery = state_dir / "house.json"
    tmp = discovery.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "port": actual_port, "token": token, "pid": os.getpid(),
        "version": __version__, "startedAt": time.time(),
    }), encoding="utf-8")
    tmp.replace(discovery)

    def ticker() -> None:
        # Keeps the world moving when nobody is asking: her current action, the
        # pots on the stove, the everyday routine. Fast while she is doing
        # something (so the picture and results are on time), slow otherwise.
        last_save = time.monotonic()
        while True:
            with house.lock:
                busy = house.world.runner.busy() or bool(house.world.jobs)
            if stop.wait(0.25 if busy else min(5.0, tick_seconds)):
                break
            house.tick()
            if time.monotonic() - last_save >= 60:
                house.save()
                last_save = time.monotonic()

    threading.Thread(target=ticker, name="house-ticker", daemon=True).start()
    threading.Thread(target=httpd.serve_forever, name="house-http", daemon=True).start()
    print(f"[little-house] listening on 127.0.0.1:{actual_port} (state: {state_dir})", flush=True)
    if window:
        if pygame_available():
            display.request(True)
        else:
            print("[little-house] 画面需要 pygame-ce：pip install pygame-ce", flush=True)
    try:
        display.run(stop)  # returns when stop is set (POST /shutdown)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
        house.save()
        httpd.server_close()
        try:
            if json.loads(discovery.read_text(encoding="utf-8")).get("pid") == os.getpid():
                discovery.unlink()
        except (OSError, ValueError):
            pass
