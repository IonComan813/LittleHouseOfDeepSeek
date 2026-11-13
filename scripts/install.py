"""Install (or uninstall) the Little House plugin into a DSH profile.

    python scripts/install.py                 # auto-detect the profile
    python scripts/install.py --profile desktop
    python scripts/install.py --uninstall

What it does (the same shape `dsh plugin add <dir>` produces, without needing
the dsh CLI or pnpm on PATH):

1. links  <DSH_HOME>/profiles/<profile>/node_modules/dsh-little-house  ->  <repo>/plugin
   (a directory junction on Windows, a symlink elsewhere);
2. adds   "dsh-little-house": "link:<repo>/plugin"  to the profile's package.json
   dependencies and appends "dsh-little-house" to dsh.profile.bundles.

package.json is backed up (package.json.bak-<timestamp>) before every change.
Restart DSH afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

NAME = "dsh-little-house"
REPO = Path(__file__).resolve().parent.parent
PLUGIN_DIR = REPO / "plugin"


def dsh_home(arg: str | None) -> Path:
    return Path(arg or os.environ.get("DSH_HOME") or Path.home() / ".dsh")


def detect_profile(home: Path) -> str:
    profiles_dir = home / "profiles"
    names = sorted(p.name for p in profiles_dir.iterdir() if (p / "package.json").exists()) if profiles_dir.exists() else []
    if not names:
        sys.exit(f"在 {profiles_dir} 下没有找到任何 DSH profile。请先启动一次 DSH，或用 --profile 指定。")
    for preferred in ("desktop", "web"):
        if preferred in names:
            if len(names) > 1:
                print(f"找到多个 profile：{', '.join(names)}；使用 {preferred}（可用 --profile 指定）")
            return preferred
    if len(names) == 1:
        return names[0]
    sys.exit(f"找到多个 profile：{', '.join(names)}，请用 --profile 指定其中一个。")


def is_link(p: Path) -> bool:
    if p.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)  # Python 3.12+
    return bool(is_junction and is_junction(p))


def make_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or is_link(link):
        if is_link(link) and Path(os.path.realpath(link)) == target.resolve():
            print(f"已存在：{link} -> {target}")
            return
        if not is_link(link):
            sys.exit(f"{link} 已存在且不是链接，为安全起见不覆盖，请手动检查。")
        remove_link(link)
    if os.name == "nt":
        try:
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        except (ImportError, AttributeError, OSError):
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)
    print(f"已链接：{link} -> {target}")


def remove_link(link: Path) -> None:
    if not is_link(link):
        return
    if os.name == "nt":
        os.rmdir(link)  # removes the junction itself, never the target's contents
    else:
        link.unlink()
    print(f"已移除链接：{link}")


def edit_package(pkg_file: Path, install: bool) -> None:
    pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
    deps = pkg.setdefault("dependencies", {})
    bundles = pkg.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
    link_value = "link:" + PLUGIN_DIR.as_posix()
    changed = False
    if install:
        if deps.get(NAME) != link_value:
            deps[NAME] = link_value
            changed = True
        if NAME not in bundles:
            bundles.append(NAME)
            changed = True
    else:
        if NAME in deps:
            del deps[NAME]
            changed = True
        if NAME in bundles:
            bundles.remove(NAME)
            changed = True
    if not changed:
        print(f"{pkg_file} 无需修改")
        return
    backup = pkg_file.with_name(f"package.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(pkg_file, backup)
    pkg_file.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已更新 {pkg_file}（备份：{backup.name}）")


def check_python() -> None:
    if sys.version_info < (3, 10):
        sys.exit(f"需要 Python 3.10 或更新，当前是 {sys.version.split()[0]}")


def main() -> None:
    p = argparse.ArgumentParser(description="Install the Little House plugin into a DSH profile")
    p.add_argument("--profile", help="DSH profile 名称（默认自动判断：desktop > web > 唯一的那个）")
    p.add_argument("--dsh-home", help="DSH 根目录（默认 %%USERPROFILE%%\\.dsh 或 $DSH_HOME）")
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    check_python()
    home = dsh_home(args.dsh_home)
    profile = args.profile or detect_profile(home)
    profile_dir = home / "profiles" / profile
    pkg_file = profile_dir / "package.json"
    if not pkg_file.exists():
        sys.exit(f"{pkg_file} 不存在：profile「{profile}」还没有初始化。")
    link = profile_dir / "node_modules" / NAME

    if args.uninstall:
        edit_package(pkg_file, install=False)
        remove_link(link)
        print("已卸载。重启 DSH 生效。小屋存档保留在 ~/.dsh/little-house，不会删除。")
        return

    make_link(link, PLUGIN_DIR)
    edit_package(pkg_file, install=True)
    print()
    print(f"安装完成（profile：{profile}）。接下来：")
    print("  1. 完全退出并重新打开 DSH；")
    print("  2. 大约 2 分钟后，会话列表里会出现「小屋生活 · 日期」——那就是她第一次醒来。")
    print(f"  python 命令：{sys.executable}（如果插件找不到 python，在配置里把 house.python 设成这个路径）")
    try:
        import pygame  # noqa: F401
        print("  pygame-ce 已安装：可以用 view.bat 打开只读画面，她也能 house_glance 看一眼小屋。")
    except ImportError:
        print("  提示：还没装 pygame-ce。想看像素画面（以及让她能看一眼小屋），运行：")
        print(f"    {sys.executable} -m pip install pygame-ce")


if __name__ == "__main__":
    main()
