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
from .script import ScriptError, format_results, run
from .world import Event, World

MAX_BODY = 16 * 1024


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
            self.world.tick()

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
        """PNG of the house as it looks now (needs pygame-ce; no window is opened)."""
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        try:
            from . import render
        except ImportError as e:
            raise RenderUnavailable("画面需要 pygame-ce：pip install pygame-ce") from e
        with self.lock:
            self.world.tick()
            png = render.render_png(self.world, scale)
        try:
            (self.state_dir / "latest.png").write_bytes(png)
        except OSError:
            pass
        return png

    def tick(self) -> None:
        with self.lock:
            self.world.tick()


def make_handler(house: House, token: str, on_shutdown=None):
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
                    house.world.tick()
                    text = house.world.look()
                self._send(200, {"ok": True, "text": text})
            elif path == "/help":
                self._send(200, {"ok": True, "text": help_text()})
            elif path == "/state":
                with house.lock:
                    house.world.tick()
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
                    house.world.tick()
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
                with house.lock:
                    results = run(house.world, script)
                    house.world.save(house.save_path)
            except ScriptError as e:
                self._send(200, {"ok": False, "text": f"✗ 脚本错误：{e}", "results": []})
                return
            self._send(200, {
                "ok": all(r.ok for r in results),
                "text": format_results(results),
                "results": [asdict(r) for r in results],
            })

    return Handler


def serve(state_dir: Path, port: int = 8770, tick_seconds: float = 30.0) -> None:
    house = House(state_dir)
    token = os.environ.get("LH_HOUSE_TOKEN") or secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(house, token, lambda: httpd.shutdown()))
    actual_port = httpd.server_address[1]
    discovery = state_dir / "house.json"
    tmp = discovery.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "port": actual_port, "token": token, "pid": os.getpid(),
        "version": __version__, "startedAt": time.time(),
    }), encoding="utf-8")
    tmp.replace(discovery)

    stop = threading.Event()

    def ticker() -> None:
        last_save = time.monotonic()
        while not stop.wait(tick_seconds):
            house.tick()
            if time.monotonic() - last_save >= 60:
                house.save()
                last_save = time.monotonic()

    threading.Thread(target=ticker, name="house-ticker", daemon=True).start()
    print(f"[little-house] listening on 127.0.0.1:{actual_port} (state: {state_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        house.save()
        httpd.server_close()
        try:
            if json.loads(discovery.read_text(encoding="utf-8")).get("pid") == os.getpid():
                discovery.unlink()
        except (OSError, ValueError):
            pass
