# -*- coding: utf-8 -*-
"""
B 站 Web API 最小客户端（仅依赖 requests）。

- 接口与 wbi 签名算法参考开源文档库 SocialSisterYi/bilibili-API-collect
- 只读公开数据；内置限速、风控退避重试；直连不走系统代理
- 可选 SESSDATA 登录态（提高风控阈值、解锁关注列表等）
"""
import hashlib
import random
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# wbi 混淆表（bilibili-API-collect）
MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

RISK_CODES = {-412, -352, -799}


class BiliApiError(Exception):
    def __init__(self, code, message, endpoint=""):
        super().__init__(f"[{code}] {message} ({endpoint})")
        self.code = code
        self.message = message


class BiliClient:
    def __init__(self, sessdata=None, delay=1.2, timeout=15, verbose=True):
        self.s = requests.Session()
        self.s.trust_env = False  # B 站是国内站点，忽略代理环境变量直连更稳
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        })
        if sessdata:
            self.s.cookies.set("SESSDATA", sessdata, domain=".bilibili.com")
        self.delay = delay
        self.timeout = timeout
        self.verbose = verbose
        self._last = 0.0
        self._wbi = None
        self._wbi_ts = 0.0

    def log(self, *a):
        if self.verbose:
            print(*a, flush=True)

    def _pace(self):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.3))
        self._last = time.time()

    def get(self, path, params=None, wbi=False, retries=4):
        url = path if path.startswith("http") else "https://api.bilibili.com" + path
        attempt = 0
        while True:
            self._pace()
            p = dict(params or {})
            if wbi:
                p.update(self.wbi_sign(p))
            try:
                r = self.s.get(url, params=p, timeout=self.timeout)
                j = r.json()
            except (requests.RequestException, ValueError) as e:
                j = {"code": -1, "message": f"网络错误: {e!r}"}
            code = j.get("code", -1)
            if code == 0:
                return j.get("data")
            if code in RISK_CODES and attempt < retries:
                attempt += 1
                wait = 4 * attempt + random.uniform(0, 3)
                self.log(f"  ! 风控 code={code} {path}，退避 {wait:.0f}s 重试({attempt}/{retries})")
                time.sleep(wait)
                continue
            raise BiliApiError(code, j.get("message", "unknown"), path)

    # ---------------- wbi 签名 ----------------
    def ensure_wbi(self, force=False):
        if self._wbi and not force and time.time() - self._wbi_ts < 1800:
            return self._wbi
        # 匿名访问 nav 会返回 code=-101，但 data.wbi_img 依然完整，故单独处理
        self._pace()
        r = self.s.get("https://api.bilibili.com/x/web-interface/nav", timeout=self.timeout)
        wbi = ((r.json().get("data") or {}).get("wbi_img")) or {}
        img = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
        sub = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
        self._wbi = "".join((img + sub)[i] for i in MIXIN_TAB)[:32]
        self._wbi_ts = time.time()
        return self._wbi

    def wbi_sign(self, params):
        mixin = self.ensure_wbi()
        clean = {}
        for k, v in params.items():
            v = str(v).strip()
            for ch in "!'()*":
                v = v.replace(ch, "")
            clean[k] = v
        clean["wts"] = str(int(time.time()))
        clean = dict(sorted(clean.items()))
        query = urllib.parse.urlencode(clean)
        clean["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
        return clean

    # ---------------- 会话预热 ----------------
    def warm_up(self):
        try:
            d = self.get("/x/frontend/finger/spi")
            for k, v in (("buvid3", d.get("b_3")), ("buvid4", d.get("b_4"))):
                if v:
                    self.s.cookies.set(k, v, domain=".bilibili.com")
        except BiliApiError as e:
            self.log(f"  ! spi 指纹失败: {e}")
        self._pace()
        try:
            self.s.get("https://www.bilibili.com/", timeout=self.timeout)
        except requests.RequestException:
            pass
        self.ensure_wbi()
        self.log("  初始化完成: buvid3=%s wbi=%s SESSDATA=%s" % (
            bool(self.s.cookies.get("buvid3")), bool(self._wbi),
            bool(self.s.cookies.get("SESSDATA"))))

    # ---------------- 常用接口 ----------------
    def user_card(self, mid):
        return self.get("/x/web-interface/card", {"mid": mid, "photo": "false"})

    def video_info(self, bvid):
        return self.get("/x/web-interface/view", {"bvid": bvid})

    def reply_main_page(self, oid, mode, nxt):
        """oid=aid；mode: 2=按时间 3=按热度"""
        return self.get("/x/v2/reply/wbi/main",
                        {"oid": oid, "type": 1, "mode": mode, "next": nxt, "ps": 20},
                        wbi=True)

    def reply_sub_page(self, oid, root, pn):
        return self.get("/x/v2/reply/reply",
                        {"oid": oid, "type": 1, "root": root, "pn": pn, "ps": 20},
                        wbi=True)

    def latest_videos(self, mid):
        """UP 主最近投稿（bvid/aid/title/pubdate），多策略兜底"""
        # 1) 空间投稿列表（未登录大概率 403，仍先试）
        try:
            d = self.get("/x/space/wbi/arc/search",
                         {"mid": mid, "pn": 1, "ps": 30, "order": "pubdate"}, wbi=True)
            vs = (d.get("list") or {}).get("vlist") or []
            if vs:
                return [{"bvid": v["bvid"], "aid": v["aid"], "title": v["title"],
                         "pubdate": v["created"]} for v in vs]
        except BiliApiError as e:
            self.log(f"  ! 投稿列表不可用: {e}")
        # 2) 空间动态里的视频动态
        try:
            items = self.dynamics(mid, pages=3)
            vids = []
            for it in items:
                if it.get("type") != "DYNAMIC_TYPE_AV":
                    continue
                mods = it.get("modules") or {}
                a = ((mods.get("module_dynamic") or {}).get("major") or {}).get("archive") or {}
                pub = ((mods.get("module_author") or {}).get("pub_ts")) or 0
                if a.get("bvid"):
                    vids.append({"bvid": a["bvid"], "aid": a.get("aid"),
                                 "title": a.get("title") or "", "pubdate": pub})
            if vids:
                return vids
        except BiliApiError as e:
            self.log(f"  ! 动态列表不可用: {e}")
        # 3) 搜索兜底（用 UP 名字搜视频，按 mid 过滤）
        try:
            name = self.user_card(mid).get("card", {}).get("name", "")
            d = self.get("/x/web-interface/wbi/search/type",
                         {"search_type": "video", "keyword": name, "page": 1}, wbi=True)
            vids = [{"bvid": r["bvid"], "aid": r["aid"], "title": r["title"],
                     "pubdate": r["pubdate"]}
                    for r in (d.get("result") or []) if r.get("mid") == mid]
            if vids:
                return vids
        except BiliApiError as e:
            self.log(f"  ! 搜索兜底不可用: {e}")
        return []

    def acc_info(self, mid):
        return self.get("/x/space/wbi/acc/info", {"mid": mid}, wbi=True)

    def followings(self, mid, ps=50):
        """关注列表：需登录 Cookie，且对方可能隐藏"""
        return self.get("/x/relation/followings", {"vmid": mid, "pn": 1, "ps": ps})

    def dynamics(self, mid, pages=2):
        items, offset = [], ""
        for _ in range(max(1, pages)):
            p = {"host_mid": mid, "platform": "web", "features": "itemOpusStyle"}
            if offset:
                p["offset"] = offset
            d = self.get("/x/polymer/web-dynamic/v1/feed/space", p, wbi=True)
            its = d.get("items") or []
            items.extend(its)
            offset = d.get("offset") or ""
            if not offset or not its:
                break
        return items

    def user_videos(self, mid, ps=30):
        d = self.get("/x/space/wbi/arc/search",
                     {"mid": mid, "pn": 1, "ps": ps, "order": "pubdate"}, wbi=True)
        return (d.get("list") or {}).get("vlist") or []
