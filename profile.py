# -*- coding: utf-8 -*-
"""
对可疑账号做公开资料画像：
个人卡片 / 空间动态 / 投稿标题 /（可选）关注列表 → 关键词痕迹。
只读公开数据；结果仅供研究与平台举报参考，请勿公开挂人/骚扰。

游戏/社区关键词表可选放在 game_keywords.json（与脚本同目录）：
    {"某游戏": ["关键词1", "关键词2"], ...}
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))
from bili_client import BiliClient, BiliApiError  # noqa: E402


def load_game_keywords():
    f = Path(__file__).parent / "game_keywords.json"
    if f.exists():
        try:
            return list(json.loads(f.read_text(encoding="utf-8")).items())
        except Exception as e:
            print(f"! game_keywords.json 解析失败: {e}")
    return []


def dyn_display_texts(items, limit=10):
    out = []
    for it in items:
        md = (it.get("modules") or {}).get("module_dynamic") or {}
        t = ((md.get("desc") or {}).get("text") or "").strip()
        if t:
            out.append(t)
        major = md.get("major") or {}
        if major.get("type") == "MAJOR_TYPE_ARCHIVE" and (major.get("archive") or {}).get("title"):
            out.append("[视频] " + major["archive"]["title"])
        elif major.get("type") == "MAJOR_TYPE_OPUS" and (major.get("opus") or {}).get("title"):
            out.append("[图文] " + major["opus"]["title"])
    seen, res = set(), []
    for t in out:
        k = t[:30]
        if k not in seen:
            seen.add(k)
            res.append(t)
        if len(res) >= limit:
            break
    return res


def scan_keywords(blob, keyword_table):
    blob_l = blob.lower()
    hits = {}
    for name, kws in keyword_table:
        found = []
        for kw in kws:
            cnt = blob_l.count(kw.lower())
            if cnt:
                found.append(f"{kw}×{cnt}")
        if found:
            hits[name] = found
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--top", type=int, default=20, help="画像的可疑账号数量")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--followings", action="store_true",
                    help="尝试抓关注列表（需登录 Cookie，且对方未隐藏）")
    ap.add_argument("--sessdata", default=os.environ.get("BILI_SESSDATA", ""))
    args = ap.parse_args()

    data = Path(args.data)
    ana_f = data / "analysis.json"
    if not ana_f.exists():
        print("!! 缺 analysis.json，先运行 analyze.py")
        sys.exit(1)
    ana = json.loads(ana_f.read_text(encoding="utf-8"))
    cands = [u for u in (ana.get("suspicious") or []) if u.get("official_type") not in (0, 1)]
    cands = cands[: args.top]
    if not cands:
        print("没有可疑账号可画像")
        sys.exit(0)

    kw_table = load_game_keywords()
    if not kw_table:
        print("提示: 未提供 game_keywords.json，将只做资料画像，不做关键词痕迹扫描")

    c = BiliClient(sessdata=args.sessdata, delay=args.delay)
    c.warm_up()

    out_f = data / "profiles.jsonl"
    n_ok = 0
    with out_f.open("w", encoding="utf-8") as f:
        for i, u in enumerate(cands, 1):
            mid = u["mid"]
            print(f"[{i}/{len(cands)}] {u.get('uname')} ({mid}) score={u.get('score')}")
            rec = {"mid": mid, "uname": u.get("uname"), "score": u.get("score"),
                   "comment_stats": {k: u.get(k) for k in
                                     ("n", "dup_ratio", "burst_ratio", "freq_per_min",
                                      "span_min", "level", "medal_name", "location")},
                   "fetched_at": int(time.time()), "errors": {}}
            blobs = []
            try:
                d = c.user_card(mid)
                card = d.get("card") or {}
                rec["card"] = {
                    "name": card.get("name"),
                    "sex": card.get("sex"),
                    "sign": (card.get("sign") or "")[:100],
                    "level": (card.get("level_info") or {}).get("current_level"),
                    "fans": d.get("follower"),
                    "attention": card.get("attention"),
                    "archive_count": card.get("archive_count"),
                    "article_count": card.get("article_count"),
                    "official": (card.get("official") or {}).get("title") or None,
                    "vip_type": (card.get("vip") or {}).get("vipType"),
                }
                if rec["card"]["sign"]:
                    blobs.append(rec["card"]["sign"])
                n_ok += 1
            except BiliApiError as e:
                rec["errors"]["card"] = str(e)
            if args.followings:
                try:
                    flw = c.followings(mid) or []
                    names = [(x.get("uname") or "", (x.get("sign") or "")) for x in flw]
                    rec["followings"] = {"visible": True, "count_returned": len(names),
                                         "sample": [x[0] for x in names[:15]]}
                    blobs.append(" ".join(a + " " + b for a, b in names))
                except BiliApiError as e:
                    rec["followings"] = {"visible": False, "error": str(e)}
            try:
                items = c.dynamics(mid, pages=2)
                texts = dyn_display_texts(items)
                rec["dynamics"] = {"n_items": len(items), "samples": texts}
                blobs.append(json.dumps(items, ensure_ascii=False))
            except BiliApiError as e:
                rec["dynamics"] = {"error": str(e)}
            try:
                vids = c.user_videos(mid)
                rec["videos"] = {"n": len(vids),
                                 "titles": [x.get("title") for x in vids[:10]]}
                blobs.append(" ".join(x.get("title") or "" for x in vids))
            except BiliApiError as e:
                rec["videos"] = {"error": str(e)}
            hits = scan_keywords(" \n ".join(blobs), kw_table)
            rec["keyword_hits"] = hits
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    print(f"== 画像完成 {n_ok}/{len(cands)} → {out_f}")


if __name__ == "__main__":
    main()
