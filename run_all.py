# -*- coding: utf-8 -*-
"""一键流水线：crawl → analyze → profile → report"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run(script, extra):
    cmd = [sys.executable, str(Path(__file__).parent / script)] + extra
    print("\n==>", " ".join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"{script} 失败，流水线中止（退出码 {r.returncode}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", type=int, required=True, help="UP 主 UID")
    ap.add_argument("--bvid", default="", help="指定视频 BV 号（默认自动取最新）")
    ap.add_argument("--max-comments", type=int, default=6000)
    ap.add_argument("--top", type=int, default=20, help="成分画像账号数")
    ap.add_argument("--sub-replies", action="store_true")
    ap.add_argument("--sessdata", default="")
    a, rest = ap.parse_known_args()

    crawl_args = ["--uid", str(a.uid), "--max-comments", str(a.max_comments)]
    if a.bvid:
        crawl_args += ["--bvid", a.bvid]
    if a.sub_replies:
        crawl_args += ["--sub-replies"]
    if a.sessdata:
        crawl_args += ["--sessdata", a.sessdata]
    run("crawl.py", crawl_args + rest)
    run("analyze.py", [])
    run("profile.py", ["--top", str(a.top)])
    run("report.py", [])
    print("\n全部完成 → report.md")


if __name__ == "__main__":
    main()
