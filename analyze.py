# -*- coding: utf-8 -*-
"""
评论数据分析：刷屏 / 疑似水军启发式检测 + 情感/立场分类。
输入 data/replies.jsonl，输出 analysis.json、CSV、图表。
评分是启发式规则（权重可在本文件调整），结果≠实锤。
"""
import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False
    HAVE_PLT = True
except Exception:
    HAVE_PLT = False

# ---------------- 情感/立场分类（人工标注高频文本 + 社区黑话规则） ----------------
# label: P=正面/庆祝  N=负面/嘲讽/引战  M=中性/灌水/表情/其他  I=组织性刷评指令
# dir:   y=支持本视频/本社区  m=嘲讽竞品社区  b=嘲讽本视频/本社区  0=无方向
#
# 下面的正则是**通用兜底规则**。不同社区都有自己的黑话（角色蔑称、厂商梗、
# 缩写、引号暗语等），通用模型无法识别反讽——建议针对目标社区：
#   1) 把评论量 top 的高频文本导出后人工标注成 data/label_map.json（键=norm_text
#      归一化文本，值={"label": P/N/M/I, "dir": y/m/b/0}），程序优先采用；
#   2) 再把社区特有黑话补充进下面的 pattern。
POS_PAT = re.compile(
    r"加油|支持|太好(看|听)|太美|神了|泪目|欢迎回家|永远喜欢|萌萌哒|爱了爱了")
MOCK_RIVAL_PAT = re.compile(r"(?!x)x")  # 永不匹配；按目标社区补充黑话后再启用
MOCK_SELF_PAT = re.compile(r"(?!x)x")
INST_PAT = re.compile(
    r"接力|转发：请大家|主页举报|一律举报|举报流程|点踩|别刷自家|去隔壁刷|纯净的图"
    r"|别给他们画面|多人举报|进主页举报")
NEU_PAT = re.compile(
    r"你说的对，但是|百度百科|维基百科|梗百科|复读机|复读")

LABEL_CN = {"P": "正面", "N": "负面", "M": "中性", "I": "刷评指令"}
DIR_CN = {"y": "支持方", "m": "嘲讽竞品", "b": "嘲讽本方", "0": "无方向"}


def classify_sentiment(text):
    """返回 (label, dir)。优先级：指令 > 嘲讽 > 正面 > 中性。"""
    t = (text or "").strip()
    core = re.sub(r"\[[^\]]{1,14}\]", "", t)
    core = re.sub(r"[^\u4e00-\u9fffa-zA-Z]", "", core)
    if INST_PAT.search(t):
        return "I", "y"
    m_r = MOCK_RIVAL_PAT.search(t)
    m_s = MOCK_SELF_PAT.search(t)
    if m_r and (not m_s or m_r.start() <= m_s.start()):
        return "N", "m"
    if m_s:
        return "N", "b"
    if POS_PAT.search(t):
        return "P", "y"
    if NEU_PAT.search(t):
        return "M", "0"
    if len(core) <= 2:
        return "M", "0"
    return "M", "0"


def norm_text(t):
    t = (t or "").lower()
    return re.sub(r"[^\u4e00-\u9fffa-z0-9]+", "", t)


def template_key(t):
    k = norm_text(t)
    k = re.sub(r"\d+", "#", k)
    k = re.sub(r"(.)\1+", r"\1", k)  # 叠字压缩：哈哈哈哈→哈
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(__file__).parent / "data"))
    ap.add_argument("--score-threshold", type=int, default=45)
    args = ap.parse_args()
    data = Path(args.data)
    repl_f = data / "replies.jsonl"
    if not repl_f.exists():
        print("!! 找不到 replies.jsonl，先运行 crawl.py")
        sys.exit(1)

    rows = [json.loads(l) for l in repl_f.open(encoding="utf-8") if l.strip()]
    if not rows:
        print("!! 没有评论数据")
        sys.exit(1)
    for r in rows:
        # 清洗换行/控制字符，避免 CSV/图表标签出问题
        clean = lambda s: "".join(ch for ch in (s or "") if ord(ch) >= 32).replace("\r", " ").replace("\n", " ")
        r["message"] = clean(r.get("message"))
        r["sign"] = clean(r.get("sign"))
    meta = {}
    mf = data / "meta.json"
    if mf.exists():
        meta = json.loads(mf.read_text(encoding="utf-8"))

    for r in rows:
        r["minute"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ctime"])) if r.get("ctime") else "?"
        r["norm"] = norm_text(r.get("message"))
        r["tmpl"] = template_key(r.get("message"))

    # 情感/立场：人工标注（data/label_map.json）优先，其余走规则
    label_map = {}
    lm_f = data / "label_map.json"
    if lm_f.exists():
        label_map = json.loads(lm_f.read_text(encoding="utf-8"))
    for r in rows:
        r["sent_label"], r["sent_dir"] = classify_sentiment(r.get("message"))
        if label_map and r["norm"] in label_map:
            v = label_map[r["norm"]]
            r["sent_label"], r["sent_dir"] = v["label"], v["dir"]
            r["sent_gold"] = 1
        else:
            r["sent_gold"] = 0

    # 图片评论
    pic_rows = [r for r in rows if r.get("pictures")]
    img_users = defaultdict(set)
    img_count = Counter()
    for r in pic_rows:
        for u in r["pictures"]:
            img_users[u].add(r["mid"])
            img_count[u] += 1
    shared_imgs = {u: us for u, us in img_users.items() if len(us) >= 2}

    # ---------- 跨用户重复文本（复读机） ----------
    text_users = defaultdict(set)
    text_count = Counter()
    text_example = {}
    for r in rows:
        if not r["norm"]:
            continue
        text_users[r["norm"]].add(r["mid"])
        text_count[r["norm"]] += 1
        text_example.setdefault(r["norm"], r["message"])
    cross_dup = {t: us for t, us in text_users.items() if len(us) >= 2}

    # ---------- 每分钟时间分布 + 爆发窗口 ----------
    per_minute = Counter(r["minute"] for r in rows if r["minute"] != "?")
    series = []
    if per_minute:
        d0 = datetime.strptime(min(per_minute), "%Y-%m-%d %H:%M")
        d1 = datetime.strptime(max(per_minute), "%Y-%m-%d %H:%M")
        cur = d0
        while cur <= d1 and len(series) < 20000:
            k = cur.strftime("%Y-%m-%d %H:%M")
            series.append((k, per_minute.get(k, 0)))
            cur += timedelta(minutes=1)
    vals = [v for _, v in series] or [0]
    med = statistics.median(vals)
    mean = statistics.mean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    thr = max(3 * med, mean + 3 * sd, 5.0)
    burst_set = {k for k, v in series if v > thr}

    # ---------- 每个账号的行为指标 ----------
    users = defaultdict(list)
    for r in rows:
        users[r["mid"]].append(r)

    per_user = []
    for mid, rs in users.items():
        rs.sort(key=lambda x: x.get("ctime") or 0)
        n = len(rs)
        ts = [x["ctime"] for x in rs if x.get("ctime")]
        span_min = (max(ts) - min(ts)) / 60.0 if len(ts) >= 2 else 0.0
        diffs = [b - a for a, b in zip(ts, ts[1:])]
        m_diff = statistics.mean(diffs) if diffs else 0
        cv = (statistics.pstdev(diffs) / m_diff) if len(diffs) >= 2 and m_diff > 0 else None
        dup_ratio = sum(1 for x in rs if x["norm"] and x["norm"] in cross_dup) / n
        tmpls = [x["tmpl"] for x in rs if x["tmpl"]]
        template_div = (len(set(tmpls)) / len(tmpls)) if tmpls else 1.0
        burst_ratio = sum(1 for x in rs if x["minute"] in burst_set) / n
        self_texts = Counter(x["norm"] for x in rs if x["norm"])
        top_text, top_n = (self_texts.most_common(1)[0] if self_texts else ("", 0))
        cross_n = len({x["norm"] for x in rs if x["norm"] in cross_dup})
        medals = [x.get("medal_name") for x in rs if x.get("medal_name")]
        locs = [x.get("location") for x in rs if x.get("location")]
        signs = [x.get("sign") for x in rs if x.get("sign")]
        per_user.append({
            "mid": mid, "uname": rs[0].get("uname"),
            "n": n, "span_min": round(span_min, 2),
            "freq_per_min": round(n / span_min, 2) if span_min > 0 else None,
            "median_interval_s": round(statistics.median(diffs), 1) if diffs else None,
            "interval_cv": round(cv, 3) if cv is not None else None,
            "burst_ratio": round(burst_ratio, 3),
            "dup_ratio": round(dup_ratio, 3),
            "template_diversity": round(template_div, 3),
            "self_top_text": top_text[:40], "self_top_text_n": top_n,
            "cross_dup_texts_n": cross_n,
            "level": rs[0].get("level"), "vip": rs[0].get("vip"),
            "official_type": rs[0].get("official_type"),
            "medal_name": Counter(medals).most_common(1)[0][0] if medals else None,
            "medal_n": len(medals),
            "location": Counter(locs).most_common(1)[0][0] if locs else None,
            "sign": (signs[0] if signs else "")[:60],
            "is_sub_n": sum(1 for x in rs if x.get("is_sub")),
        })

    # ---------- 启发式打分 ----------
    for u in per_user:
        score, reasons = 0, []
        if u["n"] < 3:
            u["score"], u["suspicious"], u["reasons"] = 0, False, []
            continue
        if u["dup_ratio"] >= 0.6:
            score += 25; reasons.append(f"高频复读他人内容({u['dup_ratio']:.0%})")
        elif u["dup_ratio"] >= 0.3:
            score += 12; reasons.append(f"部分复读他人内容({u['dup_ratio']:.0%})")
        if u["n"] >= 5 and u["template_diversity"] <= 0.5:
            score += 20; reasons.append(f"文本高度模板化(模板多样性{u['template_diversity']})")
        if burst_set and u["burst_ratio"] >= 0.6:
            score += 15; reasons.append(f"评论集中在爆发窗口({u['burst_ratio']:.0%})")
        if u["n"] >= 8 and 0 < u["span_min"] <= 10:
            score += 15; reasons.append(f"{u['span_min']:.1f}分钟内发{u['n']}条")
        if u["interval_cv"] is not None and u["n"] >= 5 and u["interval_cv"] < 0.35:
            score += 10; reasons.append("发言间隔机械规律")
        if u["level"] is not None and u["level"] <= 2:
            score += 10; reasons.append(f"账号等级低(Lv{u['level']})")
        if u["cross_dup_texts_n"] >= 3:
            score += 10; reasons.append(f"参与{u['cross_dup_texts_n']}条跨用户复读")
        u["score"] = min(score, 100)
        u["suspicious"] = u["score"] >= args.score_threshold
        u["reasons"] = reasons

    # ---------- 汇总 ----------
    counts = sorted((u["n"] for u in per_user), reverse=True)
    top1 = max(1, round(len(counts) * 0.01))
    top5 = max(1, round(len(counts) * 0.05))
    total = len(rows)
    peak_k, peak_v = (max(per_minute.items(), key=lambda kv: kv[1]) if per_minute else ("-", 0))
    susp = [u for u in per_user if u["suspicious"]]
    susp.sort(key=lambda u: (-u["score"], -u["n"]))
    susp_mids = {u["mid"] for u in susp}

    # ---------- 情感/立场汇总 ----------
    def share(rows_sel, label):
        n = len(rows_sel) or 1
        return round(sum(1 for r in rows_sel if r["sent_label"] == label) / n, 3)

    def dirshare(rows_sel):
        n = len(rows_sel) or 1
        return {"pro_self": round(sum(1 for r in rows_sel if r["sent_dir"] == "y") / n, 3),
                "anti_rival": round(sum(1 for r in rows_sel if r["sent_dir"] == "m") / n, 3),
                "anti_self": round(sum(1 for r in rows_sel if r["sent_dir"] == "b") / n, 3),
                "none": round(sum(1 for r in rows_sel if r["sent_dir"] == "0") / n, 3)}

    susp_rows = [r for r in rows if r["mid"] in susp_mids]
    normal_rows = [r for r in rows if r["mid"] not in susp_mids]
    sentiment = {
        "method": "人工标注高频文本(data/label_map.json) + 社区黑话规则；通用情感模型无法识别反讽/黑话",
        "n_gold": sum(1 for r in rows if r.get("sent_gold")),
        "all": {"pos": share(rows, "P"), "neg": share(rows, "N"),
                "neu": share(rows, "M"), "inst": share(rows, "I")},
        "suspicious": {"pos": share(susp_rows, "P"), "neg": share(susp_rows, "N"),
                       "neu": share(susp_rows, "M"), "inst": share(susp_rows, "I")},
        "normal": {"pos": share(normal_rows, "P"), "neg": share(normal_rows, "N"),
                   "neu": share(normal_rows, "M"), "inst": share(normal_rows, "I")},
        "direction_all": dirshare(rows),
        "direction_susp": dirshare(susp_rows),
        "top_negative": [
            {"message": r["message"][:80], "dir": r["sent_dir"], "uname": r.get("uname"),
             "like": r.get("like")}
            for r in [x for x in rows if x["sent_label"] == "N"][:10]
        ],
        "top_positive": [
            {"message": r["message"][:80], "dir": r["sent_dir"], "uname": r.get("uname"),
             "like": r.get("like")}
            for r in [x for x in sorted(rows, key=lambda r: -(r.get("like") or 0))
                      if x["sent_label"] == "P"][:10]
        ],
    }

    summary = {
        "total": total,
        "roots": sum(1 for r in rows if not r["is_sub"]),
        "subs": sum(1 for r in rows if r["is_sub"]),
        "unique_users": len(users),
        "first": min((r["ctime"] for r in rows if r.get("ctime")), default=None),
        "last": max((r["ctime"] for r in rows if r.get("ctime")), default=None),
        "peak_minute": peak_k, "peak_count": peak_v,
        "burst_threshold": round(thr, 2),
        "burst_minutes": sorted(burst_set),
        "dup_text_groups": sum(1 for t in cross_dup if text_count[t] >= 2),
        "top1pct_share": round(sum(counts[:top1]) / total, 3),
        "top5pct_share": round(sum(counts[:top5]) / total, 3),
        "n_suspicious": len(susp),
        "suspicious_comment_share": round(sum(u["n"] for u in susp) / total, 3),
        "location_top": Counter(r["location"] for r in rows if r.get("location")).most_common(10),
        "medal_top": Counter(r["medal_name"] for r in rows if r.get("medal_name")).most_common(10),
        "sentiment": sentiment,
        "pictures": {
            "n_pic_comments": len(pic_rows),
            "n_unique_images": len(img_users),
            "n_shared_images": len(shared_imgs),
            "shared_examples": [
                {"img": u[-60:], "count": img_count[u], "n_users": len(img_users[u])}
                for u in sorted(shared_imgs, key=lambda u: -img_count[u])[:10]
            ],
        },
        "site_reply_count": meta.get("reply_count_site"),
        "video": {k: meta.get(k) for k in ("title", "bvid", "aid", "pubdate")},
    }

    # ---------- 落盘 ----------
    (data / "analysis.json").write_text(
        json.dumps({
            "summary": summary,
            "top_users": sorted(per_user, key=lambda u: -u["n"])[:15],
            "dup_texts": [
                {"example": text_example[t], "count": text_count[t],
                 "n_users": len(text_users[t]),
                 "users_sample": ",".join(str(x) for x in list(text_users[t])[:10])}
                for t in sorted(cross_dup, key=lambda t: -text_count[t])[:30]
            ],
            "suspicious": susp[:80],
            "score_threshold": args.score_threshold,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    with (data / "per_user.csv").open("w", newline="", encoding="utf-8-sig") as f:
        cols = ["mid", "uname", "n", "is_sub_n", "span_min", "freq_per_min",
                "median_interval_s", "interval_cv", "burst_ratio", "dup_ratio",
                "template_diversity", "self_top_text", "self_top_text_n",
                "cross_dup_texts_n", "level", "vip", "official_type",
                "medal_name", "medal_n", "location", "sign", "score", "suspicious", "reasons"]
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        for u in sorted(per_user, key=lambda u: -u["score"]):
            u2 = dict(u)
            u2["reasons"] = "；".join(u["reasons"])
            u2["suspicious"] = "Y" if u["suspicious"] else ""
            wr.writerow(u2)

    with (data / "dup_texts.csv").open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["相同文本", "出现次数", "涉及账号数", "账号样例"])
        for t in sorted(cross_dup, key=lambda t: -text_count[t])[:200]:
            wr.writerow([text_example[t], text_count[t], len(text_users[t]),
                         ",".join(str(x) for x in list(text_users[t])[:15])])

    with (data / "per_minute.csv").open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["分钟", "评论数", "是否爆发窗口"])
        for k, v in series:
            wr.writerow([k, v, "Y" if k in burst_set else ""])

    # 情感/立场标注明细（供复查）
    with (data / "sentiment.csv").open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["rpid", "账号", "标签", "立场方向", "标注来源", "点赞", "评论内容"])
        for r in rows:
            wr.writerow([r["rpid"], r.get("uname"), LABEL_CN[r["sent_label"]],
                         DIR_CN[r["sent_dir"]],
                         "人工" if r.get("sent_gold") else "规则",
                         r.get("like"), (r.get("message") or "")[:80]])

    # 图片评论清单（图片内容可另行人工/视觉分析）
    with (data / "picture_comments.csv").open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["rpid", "账号", "发布时间", "点赞", "评论文本", "图片URL", "图片是否被多账号复用"])
        for r in sorted(pic_rows, key=lambda r: -(r.get("like") or 0)):
            reused = "Y" if any(u in shared_imgs for u in r["pictures"]) else ""
            wr.writerow([r["rpid"], r.get("uname"),
                         time.strftime("%F %T", time.localtime(r["ctime"])) if r.get("ctime") else "",
                         r.get("like"), (r.get("message") or "")[:60],
                         " | ".join(r["pictures"][:3]), reused])

    # ---------- 图表 ----------
    charts = data / "charts"
    charts.mkdir(exist_ok=True)
    if HAVE_PLT:
        if series:
            xs = [k for k, _ in series]
            ys = [v for _, v in series]
            fig, ax = plt.subplots(figsize=(13, 4.2))
            colors = ["#d62728" if k in burst_set else "#4c72b0" for k, _ in series]
            ax.bar(range(len(ys)), ys, color=colors, width=1.0)
            step = max(1, len(xs) // 12)
            ax.set_xticks(range(0, len(xs), step))
            ax.set_xticklabels([xs[i][5:] for i in range(0, len(xs), step)],
                               rotation=30, fontsize=8)
            ax.set_title(f"每分钟评论数（红色=爆发窗口，阈值 {thr:.1f} 条/分钟）")
            ax.set_ylabel("评论数")
            fig.tight_layout()
            fig.savefig(charts / "time_hist.png", dpi=140)
            plt.close(fig)
        top15 = sorted(per_user, key=lambda u: -u["n"])[:15][::-1]
        if top15:
            fig, ax = plt.subplots(figsize=(9, 5.5))
            labels = [f"{u['uname'][:10]}({str(u['mid'])[-4:]})" for u in top15]
            ax.barh(labels, [u["n"] for u in top15], color="#4c72b0")
            ax.set_title("发言最多的 15 个账号")
            fig.tight_layout()
            fig.savefig(charts / "top_users.png", dpi=140)
            plt.close(fig)
        dups = sorted(cross_dup, key=lambda t: -text_count[t])[:10][::-1]
        if dups:
            fig, ax = plt.subplots(figsize=(9, 5))
            ax.barh([(text_example[t] or t)[:16] for t in dups],
                    [text_count[t] for t in dups], color="#d62728")
            ax.set_title("跨账号复读文本 Top10（出现次数）")
            fig.tight_layout()
            fig.savefig(charts / "dup_texts.png", dpi=140)
            plt.close(fig)
        a = sentiment["all"]
        fig, ax = plt.subplots(figsize=(8, 4.2))
        labels = ["正面/庆祝", "负面/嘲讽", "中性/灌水", "刷评指令"]
        vals = [a["pos"], a["neg"], a["neu"], a["inst"]]
        colors = ["#27ae60", "#c0392b", "#95a5a6", "#8e44ad"]
        bars = ax.bar(labels, [v * summary["total"] for v in vals], color=colors)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
                    f"{v:.0%}", ha="center", va="bottom", fontsize=10)
        ax.set_title("评论情感/立场分布（人工标注+黑话规则）")
        fig.tight_layout()
        fig.savefig(charts / "sentiment.png", dpi=140)
        plt.close(fig)

    # ---------- 控制台摘要 ----------
    print(f"总评论 {summary['total']}（主楼 {summary['roots']} / 楼中楼 {summary['subs']}），"
          f"唯一账号 {summary['unique_users']}")
    print(f"高峰分钟: {peak_k}（{peak_v} 条）；爆发窗口 {len(burst_set)} 分钟（阈值 {thr:.1f}）")
    print(f"跨账号重复文本 {summary['dup_text_groups']} 组；"
          f"top1% 账号贡献 {summary['top1pct_share']:.0%}，top5% 贡献 {summary['top5pct_share']:.0%}")
    print(f"疑似水军账号 {len(susp)} 个（评分≥{args.score_threshold}），"
          f"其评论占总数 {summary['suspicious_comment_share']:.0%}")
    a = sentiment["all"]
    d = sentiment["direction_all"]
    print(f"情感/立场: 正面{a['pos']:.0%} 负面{a['neg']:.0%} 中性{a['neu']:.0%} 指令{a['inst']:.0%} | "
          f"方向: 支持方{d['pro_self']:.0%} 嘲讽竞品{d['anti_rival']:.0%} 嘲讽本方{d['anti_self']:.0%}（人工标注覆盖 "
          f"{sentiment['n_gold'] / summary['total']:.0%}）")
    print(f"图片评论 {len(pic_rows)} 条，唯一图片 {len(img_users)} 张，"
          f"被多账号复用 {len(shared_imgs)} 张")
    for u in susp[:10]:
        print(f"  [{u['score']:>3}] {u['uname']}({u['mid']}) n={u['n']} "
              f"dup={u['dup_ratio']:.0%} burst={u['burst_ratio']:.0%} Lv{u['level']} | "
              + "；".join(u["reasons"][:3]))


if __name__ == "__main__":
    main()
