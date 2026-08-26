#!/usr/bin/env python3
"""
fetch_bookmarks.py — 从 Firefox places.sqlite 生成 start-page 的 data.json

原理:
  1. 复制 Firefox 的 places.sqlite(-wal/-shm) 到临时目录, 避免锁冲突
  2. 读取历史记录(visit_count) + 收藏夹(文件夹名)
  3. 按域名聚合(消除 Gmail/日历/session 等 URL 变体), 选"代表 URL"
  4. 分类: 收藏夹文件夹优先, 否则域名规则表
  5. 输出 data.json (不包含访问次数 — 隐私)

用法:
  python3 fetch_bookmarks.py            # 生成 data.json
  python3 fetch_bookmarks.py --dry-run  # 只打印预览, 不写文件
  python3 fetch_bookmarks.py --limit 60
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ---------------------------------------------------------------- 配置区 ---

# 收藏夹文件夹 → 友好分类名 (未列出的用原名)
FOLDER_RENAME = {
    "toolbar": "常用",
    "unfiled": "其他",
    "Mozilla Firefox": "其他",
    "2025-05": "归档",
}

# 域名后缀(小写, 匹配 host 结尾) → 分类
DOMAIN_CATEGORY = [
    ("arxiv.org", "文献"),
    ("sciencedirect.com", "文献"),
    ("wiley.com", "文献"),
    ("nature.com", "文献"),
    ("science.org", "文献"),
    ("iopscience.iop.org", "文献"),
    ("pubs.acs.org", "文献"),
    ("aps.org", "文献"),
    ("ieee.org", "文献"),
    ("ncbi.nlm.nih.gov", "文献"),
    ("pubmed", "文献"),
    ("researchgate.net", "文献"),
    ("semanticscholar.org", "文献"),
    ("scholar.google.com", "文献"),
    ("x-mol.com", "文献"),
    ("bilibili.com", "视频"),
    ("iyf.tv", "视频"),
    ("youtube.com", "视频"),
    ("youtu.be", "视频"),
    ("douyin.com", "视频"),
    ("iqiyi.com", "视频"),
    ("chatgpt.com", "AI"),
    ("deepseek.com", "AI"),
    ("claude.ai", "AI"),
    ("perplexity.ai", "AI"),
    ("gemini.google.com", "AI"),
    ("google.com", "工具"),
    ("googleusercontent.com", "工具"),
    ("outlook.office.com", "工具"),
    ("outlook.com", "工具"),
    ("notion.so", "工具"),
    ("github.com", "工具"),
    ("stackoverflow.com", "工具"),
    ("overleaf.com", "工具"),
    ("spotify.com", "工具"),
    ("weibo.com", "社交"),
    ("zhihu.com", "社交"),
    ("xiaohongshu.com", "社交"),
    ("reddit.com", "社交"),
    ("x.com", "社交"),
    ("z.ai", "AI"),
    ("ollama.com", "AI"),
    ("umd.edu", "UMD"),
    ("nanocenter.umd.edu", "UMD"),
]

# 强制分类: host 后缀 → 分类 (优先级最高, 覆盖收藏夹文件夹)
SPECIAL_FOLDER = {
    "mail.google.com": "常用",
    "calendar.google.com": "常用",
    "outlook.office.com": "常用",
    "outlook.cloud.microsoft": "常用",
    "outlook.office365.com": "常用",
    "youtube.com": "视频",
    "scholar.google.com": "文献",
    "myaccount.acs.org": "文献",
    "mc.manuscriptcentral.com": "文献",
    "spintronics.mit.edu": "文献",
    "qm.mit.edu": "文献",
    "sunlab.wordpress.ncsu.edu": "文献",
    "notegpt.io": "视频",
    "yfsp.tv": "视频",
    "panda985.com": "视频",
    "jiarjiar.github.io": "UMD",
    "myworkday.com": "UMD",
    "umd-dining.s.gy": "UMD",
    "app.box.com": "工具",
    "drive.google.com": "工具",
    "linkedin.com": "社交",
    "101weiqi.com": "围棋",
    "19x19.com": "围棋",
}

# 手动补充的站点 (即使不在 TOP 50 也强制加入; 排序在置顶之后、普通之前)
EXTRA_SITES = [
    {"url": "https://platform.kimi.ai/console/account", "title": "Kimi API 平台", "folder": "AI"},
    {"url": "https://www.kimi.com/", "title": "Kimi 网页版", "folder": "AI"},
    {"url": "https://www.101weiqi.com/", "title": "101围棋网", "folder": "围棋"},
    {"url": "https://19x19.com/engine/index", "title": "19×19 围棋AI引擎", "folder": "围棋"},
]

# 代表 URL 模板规则: host 后缀 → 目标 URL (命中即用, 优先级高于清理逻辑)
REPRESENTATIVE = {
    "chatgpt.com": "https://chatgpt.com/",
    "platform.deepseek.com": "https://platform.deepseek.com/usage",
    "github.com": "https://github.com/",
}

# REPRESENTATIVE 模板命中时的显示标题
REP_TITLES = {
    "chatgpt.com": "ChatGPT",
    "platform.deepseek.com": "DeepSeek 开放平台",
    "github.com": "GitHub",
}

# 噪音 host (整站排除)
NOISE_HOSTS = {"bing.com", "duckduckgo.com", "search.yahoo.com", "baidu.com"}

# 跟踪参数前缀 (从查询串里丢弃)
TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"ref", "ref_src", "ref_url", "gclid", "igshid", "spm", "referer"}


def matches_pin(url: str, host: str, pin: str) -> bool:
    """置顶匹配: 完整 URL 用前缀, host 精确匹配 (避免子域/子串误伤, 如 sora.chatgpt.com)。"""
    if "://" in pin:
        return url.startswith(pin)
    return host == pin


def load_custom() -> dict:
    """读取 custom.json: 隐藏/改名/换链接 规则 (可由网页编辑模式导出)。"""
    custom = {"hidden": [], "rename": {}, "override_url": {}}
    f = Path("custom.json")
    if f.is_file():
        try:
            custom.update(json.loads(f.read_text()))
        except Exception as e:
            print(f"⚠️ custom.json 解析失败({e}), 忽略")
    return custom


def apply_custom(items: list, custom: dict) -> list:
    """应用隐藏/改名/换链接规则。"""
    out = []
    for it in items:
        if any(matches_pin(it["url"], it["host"], h) for h in custom.get("hidden", [])):
            continue
        it = dict(it)
        if it["host"] in custom.get("rename", {}):
            it["title"] = custom["rename"][it["host"]]
        if it["host"] in custom.get("override_url", {}):
            it["url"] = custom["override_url"][it["host"]]
        out.append(it)
    return out

# ---------------------------------------------------------------- 工具函数 ---


def find_profile_db() -> Path | None:
    """定位 Firefox 的 places.sqlite (优先 default-release)。"""
    base = Path.home() / "Library" / "Application Support" / "Firefox" / "Profiles"
    if not base.is_dir():
        return None
    profs = [p for p in base.iterdir() if p.is_dir()]
    prefer = [p for p in profs if "default-release" in p.name]
    prefer += [p for p in profs if p.name.endswith(".default")]
    prefer += profs
    for prof in prefer:
        db = prof / "places.sqlite"
        if db.is_file():
            return db
    return None


def read_db(db: Path) -> sqlite3.Connection:
    """复制数据库到临时目录, 避免 Firefox 占用/锁冲突。"""
    tmp = Path(tempfile.mkdtemp(prefix="places-"))
    for f in db.parent.glob(db.name + "*"):
        shutil.copy2(f, tmp / f.name)
    return sqlite3.connect(f"file:{tmp}/{db.name}?mode=ro", uri=True), tmp


def norm_host(host: str) -> str:
    h = host.lower().removeprefix("www.")
    return h


def clean_title(t: str, host: str) -> str:
    """清洗无意义的页面标题 (403/404/Error 等), 用 host 兜底。"""
    if not t or re.search(r"^(40[134]|50[025]|not found|access denied|error|forbidden)", t, re.I):
        return host
    return t


def clean_url(url: str, host: str) -> str:
    """去跟踪参数; gmail 类保留片段(#inbox/#sent); 其余去掉片段。"""
    parts = urlsplit(url)
    q = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(TRACKING_PREFIXES)
        and k.lower() not in TRACKING_KEYS
    ]
    keep_frag = "mail.google.com" in host or "groups.google.com" in host
    fragment = parts.fragment if keep_frag else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), fragment))


def is_noise(url: str, host: str) -> bool:
    """过滤搜索/重定向/内部页。"""
    if host in NOISE_HOSTS:
        return True
    parts = urlsplit(url)
    path = parts.path.lower()
    query = {k.lower() for k, _ in parse_qsl(parts.query)}
    if host == "google.com" and (path.startswith("/url?") or path.startswith("/search") or "/#q=" in url):
        return True
    if "search" in path and "q" in query:
        return True
    if "youtube.com" in host and path.startswith(("/results", "/search")):
        return True
    if "oauth2/authorize" in path or "oauth2/auth?" in path:
        return True
    return False


def select_representative(host: str, cands: list[tuple[str, int, str]]) -> tuple[str, str]:
    """从 (url, visits, title) 候选里选出代表 URL。返回 (url, title)。"""
    # 规则表直接命中
    for suffix, target in REPRESENTATIVE.items():
        if host == suffix or host.endswith("." + suffix):
            return target, REP_TITLES.get(suffix, host)

    urls = [(c[0], c[1], c[2]) for c in cands]

    # Gmail: 先按账号(u/N)分桶求和, 取最高账号, 再选 #inbox>#sent>其他
    if "mail.google.com" in host:
        acct: dict[str, int] = defaultdict(int)
        for u, v, _ in urls:
            m = re.search(r"/u/(\d+)/", u)
            acct[m.group(1) if m else "0"] += v
        best = max(acct, key=acct.get)
        prefs = []
        for u, v, _ in urls:
            m = re.search(r"/u/(\d+)/", u)
            if m and m.group(1) == best:
                prefs.append((u, v))
        prefs.sort(key=lambda x: (-x[1]))
        # 同一账号内优先 #inbox > #sent > 其他
        def frag_rank(u):
            for i, f in enumerate(["#inbox", "#sent", "#drafts"]):
                if f in u:
                    return i
            return 3
        prefs.sort(key=lambda x: (frag_rank(x[0]), -x[1]))
        rep = prefs[0][0] if prefs else urls[0][0]
        m = re.search(r"(/mail/u/\d+/[^?]*?)($|\?)", rep)
        rep = ("https://mail.google.com" + m.group(1)) if m else rep
        return rep, "Gmail"

    # 日历: 去掉路径里的日期 (/r/week/2026/3/2 → /r/week)
    if "calendar.google.com" in host:
        rep = max(urls, key=lambda c: c[1])[0]
        rep = re.sub(r"(/r/(week|month|day))/?\d*[^?]*", r"\1", rep)
        rep = re.sub(r"(/u/\d+/r/(week|month|day))$", r"\1", rep)
        if "/r/week" not in rep and "/r/month" not in rep and "/r/day" not in rep:
            rep = "https://calendar.google.com/calendar/u/4/r/week"
        return rep, "Google Calendar"

    # 远程桌面: 去掉 session 号
    if "remotedesktop.google.com" in host:
        rep = max(urls, key=lambda c: c[1])[0]
        rep = re.sub(r"/session/\w+", "/", rep)
        rep = re.sub(r"(/u/\d+/access/?)$", r"\1", rep)
        return rep, "Chrome Remote Desktop"

    # Wiley 登录跳转 → 主站
    if "wiley.com" in host and "/action/oidcStart" in urls[0][0]:
        return "https://onlinelibrary.wiley.com/", "Wiley Online Library"

    # Outlook/office mail
    if "outlook.office.com" in host or "outlook.com" in host:
        rep = max(urls, key=lambda c: c[1])[0]
        m = re.search(r"(/mail/\w+)", rep)
        rep = ("https://outlook.office.com" + m.group(1)) if m else "https://outlook.office.com/mail/"
        return rep, "Outlook"

    # 通用: 访问量最高的一条, 清理参数
    rep_url, v, rep_title = max(urls, key=lambda c: c[1])
    return clean_url(rep_url, host), clean_title(rep_title, host)


# ---------------------------------------------------------------- 主流程 ---


def build_items(conn, limit, pins):
    # 历史: url → (visits, title)
    hist: dict[str, tuple[int, str]] = {}
    for url, v, t in conn.execute(
        "SELECT url, COALESCE(visit_count,0), COALESCE(title,'') FROM moz_places WHERE url LIKE 'http%' OR url LIKE 'https%'"
    ):
        if url not in hist or v > hist[url][0]:
            hist[url] = (v, t)

    # 收藏夹: url → 文件夹名 (type=1 bookmark)
    bookmark_folder: dict[str, str] = {}
    for url, folder in conn.execute(
        """SELECT p.url, COALESCE((SELECT title FROM moz_bookmarks WHERE id=b.parent),'')
           FROM moz_bookmarks b JOIN moz_places p ON b.fk=p.id WHERE b.type=1"""
    ):
        bookmark_folder.setdefault(url, folder or "其他")

    # 聚合: norm_host → 候选 (同时统计域名合计访问量)
    agg: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    totals: dict[str, int] = defaultdict(int)
    for url, (v, title) in hist.items():
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        scheme, host = parts.scheme.lower(), parts.netloc.lower()
        if scheme not in ("http", "https") or not host:
            continue
        host = norm_host(host)
        if is_noise(url, host):
            continue
        agg[host].append((url, v, title))
        totals[host] += v

    items = []
    for host, cands in agg.items():
        cands.sort(key=lambda c: -c[1])
        rep, rep_title = select_representative(host, cands)
        if is_noise(rep, host):
            continue
        # 分类: SPECIAL强制 > 收藏夹文件夹 > 域名规则 > 其他
        folder = None
        for suffix, cat in SPECIAL_FOLDER.items():
            if host == suffix or host.endswith("." + suffix):
                folder = cat
                break
        if not folder:
            for u, v, _ in cands:
                if u in bookmark_folder:
                    folder = bookmark_folder[u]
                    break
        if not folder:
            for u, v, _ in cands:
                for suffix, cat in DOMAIN_CATEGORY:
                    if host == suffix or host.endswith("." + suffix):
                        folder = cat
                        break
                if folder:
                    break
        folder = FOLDER_RENAME.get(folder, folder or "其他")
        title = rep_title or host
        items.append(
            {
                "url": rep,
                "title": title,
                "host": host,
                "folder": folder,
                "pinned": any(matches_pin(rep, host, p) for p in pins),
            }
        )

    # 排序: 置顶优先(保持 pins.json 顺序) → 手动补充 → 其余按域名合计访问量降序
    def sort_key(it):
        v = totals.get(it["host"], 0)
        if it.get("_extra"):
            return (0.5, 0, 0)
        if it["pinned"]:
            idx = next(
                (i for i, p in enumerate(pins) if matches_pin(it["url"], it["host"], p)), 99
            )
            return (0, idx, -v)
        return (1, 0, -v)

    items.sort(key=sort_key)
    items = items[:limit]

    # 手动补充站点: 先截断再按 host 去重 (Kimi 等可能已在全量列表里)
    existing_hosts = {it["host"] for it in items}
    for es in EXTRA_SITES:
        h = norm_host(urlsplit(es["url"]).netloc)
        if h in existing_hosts:
            continue
        existing_hosts.add(h)
        items.append(
            {
                "url": es["url"],
                "title": es["title"],
                "host": h,
                "folder": es.get("folder", "其他"),
                "pinned": es.get("pinned", False),
                "_extra": True,
            }
        )
    items.sort(key=sort_key)  # 含 extras 重排 (排在置顶之后、普通之前)
    return items, agg, totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true", help="只打印预览")
    ap.add_argument("--db", type=Path, default=None, help="直接指定 places.sqlite")
    args = ap.parse_args()

    db = args.db or find_profile_db()
    if not db:
        sys.exit("❌ 找不到 Firefox places.sqlite; 请先启动过 Firefox, 或用 --db 指定路径")

    pins = []
    pinf = Path("pins.json")
    if pinf.is_file():
        pins = json.loads(pinf.read_text()).get("pins", [])

    conn, tmpdir = read_db(db)
    try:
        items, agg, totals = build_items(conn, args.limit, pins)
    finally:
        conn.close()

    custom = load_custom()
    items = apply_custom(items, custom)

    # 预览(仅本地打印, 不写入 data.json)
    print(f"✅ 共 {len(items)} 条 (来自 {len(agg)} 个域名)")
    print(f"{'访问':>6}  {'分类':<8}  {'代表URL':<45}  host")
    print("-" * 90)
    for it in items:
        v = totals.get(it["host"], 0)
        flag = "📌" if it["pinned"] else "  "
        print(f"{flag}{v:>5}  {it['folder']:<8}  {it['url'][:44]:<45}  {it['host']}")

    if not args.dry_run:
        out = {
            "updated": datetime.now().isoformat(timespec="seconds"),
            "items": [{k: it[k] for k in ("url", "title", "host", "folder", "pinned")} for it in items],
        }
        Path("data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"\n📝 已写入 data.json ({len(out['items'])} 条, 无访问次数)")


if __name__ == "__main__":
    main()
