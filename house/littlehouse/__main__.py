"""Entry point: ``python -m littlehouse [--state-dir DIR] [--port N] [--repl | --view | --screenshot PNG]``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def default_state_dir() -> Path:
    return Path(os.environ.get("LH_STATE_DIR") or Path.home() / ".dsh" / "little-house" / "world")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="littlehouse", description="Little House world server")
    p.add_argument("--state-dir", type=Path, default=default_state_dir())
    p.add_argument("--port", type=int, default=8770, help="0 = pick a free port")
    p.add_argument("--repl", action="store_true", help="play in the terminal instead of serving")
    p.add_argument("--view", action="store_true", help="open the read-only window onto the running house")
    p.add_argument("--scale", type=int, default=2, help="window scale for --view (1-4)")
    p.add_argument("--screenshot", type=Path, help="write one PNG of the saved house and exit")
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage

    if args.view:
        from .viewer import view

        view(args.state_dir, max(1, min(4, args.scale)))
        return 0

    if args.screenshot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        from . import render
        from .world import World

        world = World()
        world.load(args.state_dir / "world.json")
        args.screenshot.write_bytes(render.render_png(world, max(1, min(4, args.scale))))
        print(f"saved {args.screenshot}")
        return 0

    if args.repl:
        from .repl import repl

        repl(args.state_dir)
        return 0

    from .server import serve

    serve(args.state_dir, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
