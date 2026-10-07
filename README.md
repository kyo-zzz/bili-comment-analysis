# bili-comment-analysis

B 站视频评论区的「刷屏 / 疑似水军」分析工具箱：抓取评论 → 启发式检测协调刷评行为 →
对高频可疑账号抓取**公开**资料做「成分」画像 → 生成 Markdown 报告。

接口与 wbi 签名算法参考开源文档
[SocialSisterYi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)。

## 合规与免责声明（使用前必读）

- 本工具**仅读取任何登录访客都能看到的公开数据**（评论、用户卡片、空间动态、投稿列表），
  不破解任何权限、不绕过登录墙；登录态使用的是你自己的账号 Cookie。
- B 站用户协议对自动化访问有限制。使用本工具属于你与平台之间的行为，
  **可能触发风控（-412/-352）、限流甚至账号处罚，风险自担**。请保持默认限速，勿用于高频采集。
- 评论区内容（含昵称、UID、IP 属地）涉及他人个人信息。分析结果**仅供个人研究、
  学习或向平台举报参考**，请勿公开挂人、人肉、骚扰任何账号——启发式评分会误伤真人。
- 请遵守你所在地关于数据保护的法律法规（如《个人信息保护法》），妥善保管抓取的数据，
  不要公开传播他人的评论与账号信息。
- 本项目按 MIT 许可开源，作者不对使用者的具体用法承担责任。

## 功能

- `crawl.py`：抓取视频评论（主楼 + 可选楼中楼），限速、断点续爬、支持登录态
- `analyze.py`：爆发窗口检测、跨账号复读文本聚类、模板化分析、每账号行为指标与可疑评分、
  图片评论同源检测、情感/立场分类
- `profile.py`：对 top 可疑账号抓公开资料（等级/粉丝/签名/动态/投稿/可选关注列表）做关键词痕迹画像
- `report.py`：汇总生成 Markdown 报告（含图表）
- `run_all.py`：一键流水线
- `merge_raw.py`：合并分批抓取的 `data/raw/*.json`（用于浏览器等外部渠道采集的批次合并）

## 安装

```bash
pip install requests matplotlib        # matplotlib 可选，缺了只是没图表
```

Python ≥ 3.9。数据、图表、报告全部输出在本地 `data/` 与 `report.md`。

## 一键运行

```bash
python run_all.py --uid <UP主UID>                    # 自动取该 UP 最新视频
python run_all.py --uid <UP主UID> --bvid BV1xxxx     # 指定视频
python run_all.py --uid <UP主UID> --max-comments 20000 --sub-replies   # 爬更多 + 楼中楼
python run_all.py --uid <UP主UID> --sessdata "xxx" --top 30            # 挂登录态（推荐）
```

## 分步运行

```bash
python crawl.py --uid <UP主UID>          # 1) 抓评论 → data/replies.jsonl（断点续爬）
python analyze.py                        # 2) 分析 → data/analysis.json + CSV + 图表
python profile.py --top 20               # 3) 可疑账号公开资料画像 → data/profiles.jsonl
python report.py                         # 4) 汇总 → report.md
```

## 关键参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--uid` | 必填 | UP 主 UID |
| `--bvid` | 自动最新 | 直接指定视频 |
| `--max-comments` | 6000 | 主楼评论上限（时间序优先抓最新的） |
| `--mode` | both | time=按时间 / hot=按热度 / both |
| `--sub-replies` | 关 | 同时抓楼中楼 |
| `--delay` | 1.2s | 请求间隔，被风控(-412)就调大 |
| `--sessdata` | 环境变量 `BILI_SESSDATA` | 登录 Cookie。**未登录只能看第 1 页评论** |

SESSDATA 获取：浏览器登录 B 站 → F12 → Application → Cookies → `https://www.bilibili.com` →
复制 `SESSDATA` 的值。**不要把 SESSDATA 提交进任何仓库。**

## 检测思路（analyze.py）

- **跨账号复读**：归一化文本后统计「同一段话被多少不同账号发过」——协调刷评最硬的指标；
  复读榜上的「指令型文本」（教人复制转发/分工刷图/集体举报）是组织性口径的直接证据
- **模板化**：数字/叠字归并后看文本多样性（低多样性 = 高度模板化）
- **爆发窗口**：每分钟评论数超阈值（3×中位数等）的时段，账号评论是否扎堆
- **发言节奏**：短时间内高频、发言间隔方差极小（机械规律）
- **账号质量**：等级低、无粉丝牌等白号特征
- **图片同源**：图片评论是否跨账号复用同一图 / 同批次上传（区分 bot 矩阵与真人跟风发图）
- **情感/立场**：通用情感模型（SnowNLP 等）无法识别社区黑话与反讽，本项目采用
  「人工标注高频文本（`data/label_map.json`）+ 社区黑话规则」的两级方案，
  并输出支持方/嘲讽竞品/嘲讽本方的方向分布——这是判断「社群对轰 vs 付费水军」的关键

以上加权得到 0~100 的可疑分（权重在 `analyze.py` 内可调），**启发式 ≠ 实锤**。

## 制作 label_map.json（可选但推荐）

针对你的目标社区做精准情感分类：

1. 跑一遍 `analyze.py` 后，从 `data/sentiment.csv` / `data/dup_texts.csv` 里挑出评论量
   top 的高频文本；
2. 逐条人工标注为 `P`(正面) `N`(负面) `M`(中性) `I`(刷评指令)，方向 `y`(支持方)
   `m`(嘲讽竞品) `b`(嘲讽本方) `0`(无)；
3. 写成 `data/label_map.json`，键为 `norm_text()` 归一化后的文本，值为
   `{"label": "P", "dir": "y"}`。程序会优先采用人工标注。
4. 社区特有黑话（角色蔑称、厂商梗、缩写）补充进 `analyze.py` 顶部的 pattern。

## 已知限制

- 未登录只能看第 1 页评论；登录态下评论接口有**窗口式风控**（约每 40~110 页触发一次
  412/352），冷却 3~10 分钟自动解封，抓全量需要耐心，脚本支持断点续爬
- 旧版 pn 接口有最大偏移上限（约前 1 万条），深页只能用 cursor 流（`reply/main`）
- 关注列表需登录且对方未隐藏；动态/投稿部分账号不可见——「成分」结论只是可见痕迹的下限
- 匿名状态下 UP 投稿列表经常 403，脚本会自动退回「动态/搜索」策略，都不行就 `--bvid`

## 鸣谢

- [SocialSisterYi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect)：
  本工具所有接口与签名算法的依据
