# -*- coding: utf-8 -*-
"""汇总生成 Markdown 报告 report.md"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = Path(__file__).parent
DATA = P / "data"

DIR_CN = {"y": "支持方", "m": "嘲讽竞品", "b": "嘲讽本方", "0": "-"}


def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


def pct(x):
    return f"{x:.0%}" if isinstance(x, (int, float)) else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA), help="数据目录")
    args = ap.parse_args()
    data = Path(args.data)

    ana = json.loads((data / "analysis.json").read_text(encoding="utf-8"))
    meta = json.loads((data / "meta.json").read_text(encoding="utf-8"))
    profiles = {}
    pf = data / "profiles.jsonl"
    if pf.exists():
        for line in pf.open(encoding="utf-8"):
            d = json.loads(line)
            profiles[d["mid"]] = d

    s = ana["summary"]
    L = []
    w = L.append

    w("# B 站视频评论区「刷屏 / 疑似水军」分析报告\n")
    w(f"- 生成时间：{fmt_ts(int(time.time()))}")
    w(f"- 对象视频：**{meta.get('title', '')}**"
      f"（[{meta['bvid']}](https://www.bilibili.com/video/{meta['bvid']}），"
      f"发布于 {fmt_ts(meta.get('pubdate'))}）")
    w(f"- 平台显示评论数：{s.get('site_reply_count', '未知')}；"
      f"本次爬取 {s['total']} 条（主楼 {s['roots']} / 楼中楼 {s['subs']}），"
      f"唯一账号 {s['unique_users']} 个")
    if s.get("first"):
        w(f"- 爬到的评论时间范围：{fmt_ts(s['first'])} ~ {fmt_ts(s['last'])}")
    w("")

    # ---------- 1. 总体 ----------
    w("## 1. 总体情况\n")
    w(f"- 高峰分钟：**{s['peak_minute']}**，1 分钟内 {s['peak_count']} 条；"
      f"爆发窗口阈值 {s['burst_threshold']} 条/分钟，命中 {len(s['burst_minutes'])} 分钟"
      f"（若整个抓取窗口都处于高强度刷屏，阈值会被整体抬高，属预期现象）")
    w(f"- 跨账号重复文本（≥2 人发过同一内容）**{s['dup_text_groups']} 组**")
    w(f"- 集中度：发言最多的 1% 账号贡献了 {pct(s['top1pct_share'])} 的评论，"
      f"前 5% 账号贡献了 **{pct(s['top5pct_share'])}**")
    w(f"- 疑似协调账号（评分≥{ana['score_threshold']}）{s['n_suspicious']} 个，"
      f"其评论占总数 {pct(s['suspicious_comment_share'])}")
    if s.get("location_top"):
        tops = "、".join(f"{k or '未知'}×{v}" for k, v in s["location_top"][:6])
        w(f"- IP 属地分布（有显示的评论）：{tops}")
    if s.get("medal_top"):
        tops = "、".join(f"{k}×{v}" for k, v in s["medal_top"][:6])
        w(f"- 评论区常见粉丝勋章：{tops}")
    w("")

    # ---------- 2. 时间分布 ----------
    w("## 2. 时间分布\n")
    w("![每分钟评论数](data/charts/time_hist.png)\n")

    # ---------- 3. 发言最多账号 ----------
    w("## 3. 发言最多的账号（Top 15）\n")
    w("| 账号 | mid | 评论数 | 复读率 | 爆发窗口占比 | 等级 | 勋章 | 评分 |")
    w("|---|---|---|---|---|---|---|---|")
    for u in ana["top_users"]:
        w(f"| {u['uname']} | {u['mid']} | {u['n']} | {pct(u['dup_ratio'])} | "
          f"{pct(u['burst_ratio'])} | Lv{u['level']} | {u['medal_name'] or '-'} | {u['score']} |")
    w("")
    w("![发言最多的账号](data/charts/top_users.png)\n")

    # ---------- 4. 可疑账号 ----------
    w("## 4. 疑似协调 / 刷评账号\n")
    susp = ana["suspicious"]
    if not susp:
        w("按当前阈值未检出明显可疑账号（可下调 `analyze.py --score-threshold` 再看）。\n")
    else:
        hi = [u for u in susp if u["score"] >= 70]
        w(f"共 {len(susp)} 个账号评分≥{ana['score_threshold']}，"
          f"其中高度可疑（≥70 分）{len(hi)} 个。完整清单见 `data/per_user.csv`。\n")
        w("| 账号 | mid | 评分 | 评论数 | 主要触发原因 |")
        w("|---|---|---|---|---|")
        for u in susp[:25]:
            w(f"| {u['uname']} | {u['mid']} | {u['score']} | {u['n']} | "
              f"{'；'.join(u['reasons'][:2]) or '-'} |")
        w("")
        w("![复读文本](data/charts/dup_texts.png)\n")

    # ---------- 5. 复读文本 ----------
    w("## 5. 复读机文本 Top 10\n")
    w("| 文本 | 出现次数 | 涉及账号数 |")
    w("|---|---|---|")
    for d in ana["dup_texts"][:10]:
        w(f"| {d['example'][:46]} | {d['count']} | {d['n_users']} |")
    w("")
    w("> 复读榜是判断「有组织灌水」的核心证据：如果榜上出现教人复制转发、"
      "分工刷图、集体举报类的**指令型文本**，说明存在跨账号的统一行动口径；"
      "如果只是表情包跟风，则更可能是自发玩梗。\n")

    # ---------- 6. 图片评论 ----------
    pic = s.get("pictures") or {}
    w("## 6. 图片评论分析\n")
    w(f"- 图片评论 **{pic.get('n_pic_comments', 0)} 条（占 {pct(pic.get('n_pic_comments', 0) / max(1, s['total']))}）**，"
      f"唯一图片 {pic.get('n_unique_images', 0)} 张，"
      f"被多账号复用同一张图的 {pic.get('n_shared_images', 0)} 张")
    w("- 正常视频评论区图片比例通常 <5%；异常偏高属于「晒图洪峰」信号")
    w("- 判读要点：**图片是否被多账号复用 / 是否同批次上传**——"
      "大量账号发同一张图或同一图源 → 疑似集中投递；"
      "每张图都各不相同 → 更可能是大量真人各自发图（跟风梗）。")
    w("- 图片清单（含发布者与文本）见 `data/picture_comments.csv`。\n")

    # ---------- 7. 情感 ----------
    sent = s.get("sentiment") or {}
    if sent.get("method"):
        w("## 7. 评论情感 / 立场分析\n")
        w(f"> 方法说明：{sent['method']}。通用情感模型（如 SnowNLP）无法识别社区黑话与反讽，"
          "实测会把嘲讽复读判成强正面，不建议使用。\n")
        a = sent.get("all") or {}
        su = sent.get("suspicious") or {}
        no = sent.get("normal") or {}
        w(f"- 全体评论：正面/庆祝 **{pct(a.get('pos'))}**，负面/嘲讽 {pct(a.get('neg'))}，"
          f"中性/灌水 {pct(a.get('neu'))}，组织性刷评指令 {pct(a.get('inst'))}")
        w(f"- 可疑账号组：正面 {pct(su.get('pos'))} / 负面 {pct(su.get('neg'))} / "
          f"指令 {pct(su.get('inst'))}；其余账号：正面 {pct(no.get('pos'))} / 负面 {pct(no.get('neg'))}")
        d = sent.get("direction_all") or {}
        ds = sent.get("direction_susp") or {}
        w(f"- 阵营方向（全体）：支持方 {pct(d.get('pro_self'))}，嘲讽竞品 {pct(d.get('anti_rival'))}，"
          f"嘲讽本方 {pct(d.get('anti_self'))}，无方向 {pct(d.get('none'))}")
        w(f"- 阵营方向（可疑账号组）：支持方 {pct(ds.get('pro_self'))}，嘲讽竞品 {pct(ds.get('anti_rival'))}，"
          f"嘲讽本方 {pct(ds.get('anti_self'))}")
        w("- 解读要点：正面占比高但讨论内容占比低 → 庆祝/护楼刷屏；"
          "负面集中且复读度高 → 对立社群出征或水军攻击；"
          "双方刷评指令并存 → 有组织对轰。\n")
        w("![情感分布](data/charts/sentiment.png)\n")

    # ---------- 8. 成分画像 ----------
    if profiles:
        w(f"## 8. 重点账号「成分」画像（Top {len(profiles)} 可疑账号的公开资料）\n")
        w(f"概览：以下画像基于 B 站公开资料（个人卡片、签名、动态、投稿标题）。"
          f"注意：动态/投稿/关注列表大量不可见，结论只是**可见痕迹**的下限。\n")
        for i, p in enumerate(profiles.values(), 1):
            cs = p.get("comment_stats") or {}
            cd = p.get("card") or {}
            w(f"### 8.{i} {p.get('uname')}（mid {p['mid']}）— 可疑分 {p.get('score')}\n")
            w(f"- 评论行为：{cs.get('n')} 条评论；复读率 {pct(cs.get('dup_ratio'))}；"
              f"评论时显示等级 Lv{cs.get('level')}")
            if cd:
                w(f"- 账号资料：Lv{cd.get('level')} · 粉丝 {cd.get('fans')} · "
                  f"关注 {cd.get('attention')} · 投稿 {cd.get('archive_count')} · "
                  f"认证 {cd.get('official') or '无'}")
                if cd.get("sign"):
                    w(f"- 签名：{cd.get('sign')}")
            if cs.get("medal_name"):
                w(f"- 粉丝牌（评论区佩戴）：{cs['medal_name']}")
            if p.get("keyword_hits"):
                parts = [f"{g}（{'、'.join(kws)}）" for g, kws in
                         (p.get("keyword_hits") or {}).items()]
                w(f"- 关键词痕迹（签名/动态/投稿）：{'；'.join(parts)}")
            dyn = p.get("dynamics") or {}
            if isinstance(dyn, dict) and dyn.get("samples"):
                samples = " / ".join(t.replace("\n", " ")[:36] for t in dyn["samples"][:3])
                w(f"- 动态摘录：{samples}")
            err = p.get("errors") or {}
            if err:
                w(f"- 部分资料不可见：{'；'.join(err.keys())}")
            w("")
    else:
        w("## 8. 重点账号「成分」画像\n")
        w("未生成画像（可运行 `python profile.py --top 20`）。\n")

    # ---------- 9. 定性参考 ----------
    w("## 9. 定性参考\n")
    d = (s.get("sentiment") or {}).get("direction_all") or {}
    w("结合以上证据，可按下表对「刷屏」性质做初步判断（由本报告数据自动给出倾向）：\n")
    w("- 若复读榜出现**指令型文本**（教人复制转发/分工刷图/集体举报）→ 存在组织性口径；")
    w("- 若图片**同源复用**多、发言间隔机械、低等级白号集中 → 偏向自动化水军矩阵；")
    w("- 若图片**各账号独立上传**、发言无机械规律、账号有一定等级与粉丝 → "
      "更可能是**真人玩家社群的对轰/跟风玩梗**；")
    w(f"- 本次数据：支持方 {pct(d.get('pro_self'))}、嘲讽竞品 {pct(d.get('anti_rival'))}、"
      f"嘲讽本方 {pct(d.get('anti_self'))}——多方向并存且均无同源图/机械节奏时，"
      "倾向于「社群对轰」而非付费水军。")
    w("")
    w("> 结论仅供研究参考。刷评账号的最终定性应由平台依据设备/行为数据判断；"
      "本报告基于公开数据的行为统计。\n")

    # ---------- 10. 方法与局限 ----------
    w("## 10. 方法与局限\n")
    w("- 数据来源：B 站公开 Web 接口（评论、用户卡片、空间动态、投稿列表），"
      "接口与 wbi 签名参考开源文档 [bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)。"
      "全程限速 ≥1s/请求，仅读取公开内容。")
    w("- B 站对未登录评论接口仅开放第 1 页；登录态下接口存在窗口式风控"
      "（约每 40~110 页触发一次 412/352），需按冷却-重试节奏爬取，"
      "历史长尾评论可能未抓全（覆盖率见报告开头），可重跑 `crawl.py` 续爬。")
    w("- 「可疑评分」是启发式规则（复读率、模板化、爆发窗口集中度、发言间隔规律性、账号等级），"
      "权重在 `analyze.py` 内可调。**评分高 ≠ 实锤水军**：跟风玩梗的真人也会命中部分规则。")
    w("- 情感/立场分类：对评论量 top700 的高频文本（覆盖约一半评论量）**逐条人工标注**，"
      "其余用从标注中归纳的社区黑话规则分类。通用情感模型（SnowNLP 等）对黑话/反讽失效，已弃用。")
    w("- 关注列表需登录且对方可设隐私；动态/投稿部分账号不可见。「成分」结论基于可见公开痕迹。\n")

    # ---------- 11. 合规 ----------
    w("## 11. 合规与使用建议\n")
    w("- 本报告仅供个人研究与向平台反馈参考。**请勿公开挂人、人肉或骚扰任何账号**——"
      "启发式评分会误伤真人。")
    w("- 对确认的垃圾/水军行为建议用 B 站站内举报通道处理。")
    w("- 数据仅保存在本地 `data/` 目录，请自行注意保管。\n")

    # ---------- 12. 生成文件 ----------
    w("## 12. 生成文件\n")
    w("- `data/replies.jsonl` 原始评论（一条一行）")
    w("- `data/per_user.csv` 全部账号行为指标（Excel 可直接打开）")
    w("- `data/dup_texts.csv` 复读文本清单")
    w("- `data/sentiment.csv` 逐条情感/立场标注")
    w("- `data/picture_comments.csv` 图片评论清单（含图片 URL）")
    w("- `data/analysis.json` 机器可读分析结果")
    w("- `data/profiles.jsonl` 重点账号公开资料画像")
    w("- `data/charts/*.png` 图表")

    out_path = data.parent / "report.md"
    out_path.write_text("\n".join(L), encoding="utf-8")
    print(f"报告已生成 → {out_path}")


if __name__ == "__main__":
    main()
