"""Development only: export a life session as a readable Markdown log.

    /opt/lh/venv/bin/python tools/fulllog.py <DSH_HOME> <out.md> [text in the opening message] [--diary DIR]

Picks the newest session whose first message contains the text (default: the
newest session). Shows every message the plugin sent her, her reasoning, each
house_do script with its full result, the other tool calls, token usage and,
with --diary, the diary files written that day.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import zstandard


def read_events(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if path.suffix == ".zstd":
        out = b""
        d = zstandard.ZstdDecompressor()
        while raw:  # multi-frame: decompress frame after frame
            obj = d.decompressobj()
            out += obj.decompress(raw)
            raw = obj.unused_data
        raw = out
    return [json.loads(line) for line in raw.decode().splitlines() if line.strip()]


def text_of(content: list[dict]) -> str:
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


def first_user_text(events: list[dict]) -> str:
    for e in events:
        if e["type"] == "user/message":
            return text_of(e["data"]["content"])
    return ""


def hm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def fence(text: str) -> str:
    return "```\n" + text.rstrip() + "\n```"


def export(events: list[dict]) -> str:
    head = events[0]
    out = [f"# 小屋生活完整日志：{head['id']}", ""]
    usage = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0}
    calls = 0
    for e in events:
        t, d = e["type"], e.get("data", {})
        if t == "session/title":
            out[0] = f"# {d['title']}（{head['id']}）"
        elif t == "user/message":
            text = text_of(d["content"])
            if text.startswith("<system-reminder>"):
                continue
            out += [f"## {hm(e['time'])} 插件 → 她", "", fence(text), ""]
        elif t == "assistant/message":
            calls += 1
            for k in usage:
                usage[k] += d.get("usage", {}).get(k, 0) or 0
            for c in d["message"]["content"]:
                if c["type"] == "reasoning" and c.get("text", "").strip():
                    out += [f"**{hm(e['time'])} 她在想：**", "", "> " + c["text"].strip().replace("\n", "\n> "), ""]
                elif c["type"] == "text" and c.get("text", "").strip():
                    out += [f"**{hm(e['time'])} 她说：** {c['text'].strip()}", ""]
        elif t == "tool/call":
            try:
                args = json.loads(d.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"raw": d.get("arguments")}
            if d["name"] == "house_do":
                out += [f"### {hm(e['time'])} house_do", "", fence(args.get("script", "")), ""]
            else:
                shown = json.dumps(args, ensure_ascii=False) if args else ""
                out += [f"### {hm(e['time'])} {d['name']}{(' ' + shown) if shown else ''}", ""]
        elif t == "tool/result":
            content = d["message"]["content"]
            text = text_of(content) or ("[图片]" if any(c.get("type") == "image" for c in content) else "")
            out += [f"结果（{hm(e['time'])}）：", "", fence(text), ""]
        elif t == "turn/end":
            out += [f"*— {hm(e['time'])} 这一轮结束（{d.get('reason', {}).get('kind', '')}）—*", ""]
    billed = usage["inputTokens"] - usage["cacheReadTokens"]
    out += ["## 用量", "",
            f"模型调用 {calls} 次；输入 {usage['inputTokens']} token（缓存命中 {usage['cacheReadTokens']}，计费输入约 {billed}），"
            f"输出 {usage['outputTokens']} token。", ""]
    return "\n".join(out)


def main(argv: list[str]) -> None:
    diary = None
    if "--diary" in argv:
        i = argv.index("--diary")
        diary = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    home, out = Path(argv[0]), Path(argv[1])
    needle = argv[2] if len(argv) > 2 else ""
    found = []
    for p in (home / "sessions").rglob("session.v4.jsonl*"):
        events = read_events(p)
        if events and events[0].get("type") == "session" and needle in first_user_text(events):
            found.append((events[0].get("createdAt", 0), events))
    if not found:
        sys.exit("没有找到对应的会话。")
    events = max(found, key=lambda f: f[0])[1]
    text = export(events)
    if diary and diary.exists():
        day = datetime.fromtimestamp(events[0]["createdAt"] / 1000).strftime("%Y-%m-%d")
        f = diary / f"{day}.md"
        if f.exists():
            text += "\n## 当天的日记文件\n\n" + fence(f.read_text(encoding="utf-8")) + "\n"
    out.write_text(text, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main(sys.argv[1:])
