# -*- coding: utf-8 -*-
"""
抓取 B 站视频评论 → data/replies.jsonl（断点续爬，限速）。
仅抓取公开数据；请保持限速，结果勿用于骚扰任何人。
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


def flatten_reply(r, src_mode, is_sub=False):
    m = r.get("member") or {}
    medal = r.get("fans_medal") or m.get("fans_medal") or {}
    loc = (r.get("reply_control") or {}).get("location") or ""
    pics = [p.get("img_src") for p in ((r.get("content") or {}).get("pictures") or [])
            if p.get("img_src")]
    return {
        "rpid": str(r.get("rpid_str") or r.get("rpid")),
        "oid": r.get("oid"),
        "root": str(r.get("root") or ""),
        "mid": m.get("mid"),
        "uname": m.get("uname"),
        "sex": m.get("sex"),
        "sign": (m.get("sign") or "")[:80],
        "level": (m.get("level_info") or {}).get("current_level"),
        "vip": m.get("vipStatus"),
        "official_type": (m.get("official_verify") or {}).get("type"),
        "medal_name": (medal or {}).get("medal_name") or None,
        "medal_level": (medal or {}).get("level") or None,
        "like": r.get("like"),
        "rcount": r.get("rcount"),
        "ctime": r.get("ctime"),
        "message": (r.get("content") or {}).get("message"),
        "pictures": pics,
        "location": loc.replace("IP属地：", "").replace("IP属地:", "") or None,
        "src_mode": src_mode,
        "is_sub": is_sub,
        "_crawled_at": int(time.time()),
    }


def finalize_meta(meta_f, repl_f, meta):
    total, mids, ct, modes = 0, set(), [], {"hot": 0, "time": 0, "sub": 0}
    for line in repl_f.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        total += 1
        mids.add(d.get("mid"))
        if d.get("ctime"):
            ct.append(d["ctime"])
        if d.get("is_sub"):
            modes["sub"] += 1
        else:
            modes[d.get("src_mode")] += 1
    meta.update({
        "total_comments": total, "unique_users": len(mids),
        "first_ctime": min(ct) if ct else None,
        "last_ctime": max(ct) if ct else None,
        "mode_counts": modes, "finished_at": int(time.time()),
    })
    meta_f.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="B 站视频评论抓取（公开数据/限速/可续爬）")
    ap.add_argument("--uid", type=int, required=True, help="UP 主 UID（配合自动取最新视频）")
    ap.add_argument("--bvid", default="", help="直接指定视频 BV 号（否则自动取 UP 最新视频）")
    ap.add_argument("--mode", choices=["both", "time", "hot"], default="both")
    ap.add_argument("--max-comments", type=int, default=6000, help="主楼评论条数上限")
    ap.add_argument("--max-hot-pages", type=int, default=10)
    ap.add_argument("--sub-replies", action="store_true", help="同时抓楼中楼")
    ap.add_argument("--max-sub-pages-per-root", type=int, default=4)
    ap.add_argument("--max-subs", type=int, default=3000)
    ap.add_argument("--delay", type=float, default=1.2, help="请求间隔秒")
    ap.add_argument("--sessdata", default=os.environ.get("BILI_SESSDATA", ""),
                    help="可选：登录 Cookie SESSDATA（未登录只能看第 1 页评论）")
    ap.add_argument("--out", default=str(Path(__file__).parent / "data"))
    args = ap.parse_args()

    if not args.bvid and not args.uid:
        ap.error("需要 --uid 或 --bvid 之一")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    repl_f, meta_f = out / "replies.jsonl", out / "meta.json"

    seen = set()
    if repl_f.exists():
        for line in repl_f.open(encoding="utf-8"):
            try:
                seen.add(json.loads(line)["rpid"])
            except Exception:
                pass
        print(f"断点续爬：已有 {len(seen)} 条，新增将追加")

    c = BiliClient(sessdata=args.sessdata, delay=args.delay)
    print("== 初始化（cookie / wbi 签名）==")
    c.warm_up()

    print("== 定位视频 ==")
    if args.bvid:
        v = c.video_info(args.bvid)
    else:
        card = c.user_card(args.uid)
        print(f"UP 主: {card['card']['name']} (uid={args.uid}, 粉丝 {card.get('follower')})")
        vids = c.latest_videos(args.uid)
        if not vids:
            print("!! 匿名状态下拿不到投稿列表，请用 --bvid 指定视频")
            sys.exit(1)
        vids.sort(key=lambda x: x.get("pubdate") or 0, reverse=True)
        for x in vids[:3]:
            print("   候选:", x["bvid"], (x["title"] or "")[:28])
        v = c.video_info(vids[0]["bvid"])
    oid = v["aid"]
    print(f"选定: 【{v['title']}】 bvid={v['bvid']} 平台评论数={v['stat']['reply']} "
          f"发布={time.strftime('%F %T', time.localtime(v['pubdate']))}")

    meta = {
        "uid": args.uid, "bvid": v["bvid"], "aid": oid, "title": v["title"],
        "pubdate": v["pubdate"], "reply_count_site": v["stat"]["reply"],
        "view": v["stat"]["view"],
        "args": {k: val for k, val in vars(args).items()},
        "started_at": int(time.time()),
    }
    meta_f.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    modes = ([("hot", 3)] if args.mode in ("both", "hot") else []) + \
            ([("time", 2)] if args.mode in ("both", "time") else [])

    total_new = 0
    f = repl_f.open("a", encoding="utf-8")

    def save(rep, src_mode, is_sub=False):
        nonlocal total_new
        d = flatten_reply(rep, src_mode, is_sub)
        if d["rpid"] in seen:
            return False
        seen.add(d["rpid"])
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
        total_new += 1
        return True

    try:
        for label, mode_no in modes:
            print(f"== 主楼评论 mode={label} ==")
            nxt, page, guard = 0, 0, set()
            while True:
                try:
                    d = c.reply_main_page(oid, mode_no, nxt)
                except BiliApiError as e:
                    print(f"!! 接口报错，停止本模式: {e}")
                    if e.code == -101:
                        print("   提示: 未登录只能看第 1 页评论，可设置 BILI_SESSDATA 环境变量后重试")
                    break
                page += 1
                reps = d.get("replies") or []
                cur = d.get("cursor") or {}
                if label == "time" and page == 1:
                    meta["root_total_server"] = cur.get("all_count")
                for r in reps:
                    save(r, label)
                if page % 10 == 0:
                    print(f"   [{label}] 第 {page} 页, 累计 {len(seen)} 条")
                    f.flush()
                n = cur.get("next")
                if cur.get("is_end") or not reps or n is None or n in guard:
                    print(f"   [{label}] 完成: {page} 页")
                    break
                guard.add(nxt)
                nxt = n
                if label == "time" and len(seen) >= args.max_comments:
                    print(f"   已达 --max-comments={args.max_comments}")
                    break
                if label == "hot" and page >= args.max_hot_pages:
                    print("   已达 --max-hot-pages")
                    break
            f.flush()

        if args.sub_replies:
            print("== 楼中楼 ==")
            roots = []
            for line in repl_f.open(encoding="utf-8"):
                d = json.loads(line)
                if not d["is_sub"] and (d.get("rcount") or 0) > 3:
                    roots.append(d)
            print(f"   需展开 {len(roots)} 层楼")
            sub_new = 0
            for i, root in enumerate(roots):
                if sub_new >= args.max_subs:
                    print("   已达 --max-subs")
                    break
                pn = 1
                while pn <= args.max_sub_pages_per_root:
                    try:
                        d = c.reply_sub_page(oid, root["rpid"], pn)
                    except BiliApiError:
                        break
                    reps = d.get("replies") or []
                    for r in reps:
                        if save(r, root.get("src_mode") or "time", is_sub=True):
                            sub_new += 1
                    pageinfo = d.get("page") or {}
                    if not reps or pn * (pageinfo.get("size") or 20) >= (pageinfo.get("count") or 0):
                        break
                    pn += 1
                if (i + 1) % 20 == 0:
                    print(f"   进度 {i+1}/{len(roots)}, 楼中楼新增 {sub_new}")
                    f.flush()
            f.flush()
    except KeyboardInterrupt:
        print("!! 手动中断，已保存当前进度（重跑可续爬）")
    finally:
        f.close()
        finalize_meta(meta_f, repl_f, meta)
        print(f"== 完成: 新增 {total_new} 条, 总计 {meta['total_comments']} 条, "
              f"唯一账号 {meta['unique_users']} 个 → {repl_f}")


if __name__ == "__main__":
    main()
