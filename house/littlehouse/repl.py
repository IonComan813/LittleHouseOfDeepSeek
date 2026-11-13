"""Terminal play mode: type pseudo-code, see what happens.

If a house server is already running on this state directory (for example the
one DSH started), the REPL talks to it over HTTP so there is only ever one
writer of the save file. Otherwise it loads the world itself and saves on exit.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .script import ScriptError, format_results, run
from .server import House


def _running_server(state_dir: Path) -> tuple[int, str] | None:
    try:
        info = json.loads((state_dir / "house.json").read_text(encoding="utf-8"))
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/health", timeout=2) as r:
            if json.loads(r.read()).get("ok"):
                return int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        pass
    return None


def _remote(port: int, token: str) -> tuple[Callable[[], str], Callable[[str], str]]:
    def call(method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
        req.add_header("X-House-Token", token)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    return (lambda: call("GET", "/look")["text"]), (lambda src: call("POST", "/do", {"script": src})["text"])


def repl(state_dir: Path) -> None:
    server = _running_server(state_dir)
    house: House | None = None
    if server is not None:
        print(f"（已连接到正在运行的小屋，端口 {server[0]}）")
        look, do = _remote(*server)
    else:
        house = House(state_dir)

        def look() -> str:
            with house.lock:
                house.world.tick()
                return house.world.look()

        def do(src: str) -> str:
            try:
                with house.lock:
                    return format_results(run(house.world, src))
            except ScriptError as e:
                return f"✗ 脚本错误：{e}"

    print(look())
    print("（输入伪代码，例如 goto(沙滩); look()。help() 查看动作，空行或 Ctrl+C 退出）")
    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                break
            print(do(line))
    except KeyboardInterrupt:
        pass
    finally:
        if house is not None:
            house.save()
