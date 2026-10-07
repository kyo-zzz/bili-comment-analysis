# -*- coding: utf-8 -*-
"""把 data/raw/*.json（分批抓取的原始批次文件）合并去重为 data/replies.jsonl"""
import glob
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = Path(__file__).parent
RAW = P / "data" / "raw"
OUT = P / "data" / "replies.jsonl"

rows = {}
for f in sorted(glob.glob(str(RAW / "*.json"))):
    try:
        batch = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        print("跳过损坏文件", f, e)
        continue
    for r in batch:
        rows.setdefault(r["rp"], r)

meta = {}
meta_f = P / "data" / "meta.json"
if meta_f.exists():
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
oid = meta.get("aid", 0)

with OUT.open("w", encoding="utf-8") as f:
    for r in rows.values():
        f.write(json.dumps({
            "rpid": r["rp"], "oid": oid, "root": r.get("root") or "0",
            "mid": r.get("mid"), "uname": r.get("u"), "sex": None,
            "sign": r.get("sg") or "", "level": r.get("lv"), "vip": r.get("vip"),
            "official_type": r.get("off"),
            "medal_name": r.get("md"), "medal_level": r.get("ml"),
            "like": r.get("lk"), "rcount": r.get("rc"), "ctime": r.get("ct"),
            "message": r.get("ms"), "pictures": r.get("pics") or [],
            "location": (r.get("lc") or "").replace("IP属地：", "").replace("IP属地:", "") or None,
            "src_mode": "time", "is_sub": False, "_crawled_at": int(time.time()),
        }, ensure_ascii=False) + "\n")

print(f"合并完成: {len(rows)} 条唯一评论 → {OUT}")
