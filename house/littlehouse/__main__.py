"""Entry point: ``python -m littlehouse [--state-dir DIR] [--port N] [--repl]``."""

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
    args = p.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage

    if args.repl:
        from .repl import repl

        repl(args.state_dir)
        return 0

    from .server import serve

    serve(args.state_dir, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
