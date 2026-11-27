#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
琉璃TV 远程订阅源生成器
=======================

功能：
1. 拉取上游聚合直播源与第三方直连源，兼容 m3u(#EXTINF) / txt(#genre#) /
   空行分段 / `分组#频道#地址` 四种格式；
2. 按 config.json 拆分移动、联通两份精简订阅，另出一份全集备用源；
3. 同名频道归一合并：分类列表里每个台只占一条主线路，其余线路统一收入
   「备用线路」分组供换线使用，不再出现一个台重复多个卡片；
4. 频道按 广东 / 央视 / 卫视 / 少儿 / 纪实 / 体育 / 电影剧场 / 综艺 / 音乐 /
   教育 / 地方 / 香港 / 澳门 / 咪咕 / 其他 分类输出 M3U（#EXTINF），
   可直接填入琉璃TV 订阅地址；
5. 备用线路统一写入最底部分组，不占用中间分类位置；输出不带台标图标。

本地离线自测：
    SOURCE_FILE=/path/to/上游.txt python3 scripts/build_sources.py
"""

import json
import os
import re
import urllib.request
import urllib.parse
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUT_DIR = os.path.join(BASE_DIR, "sources")
SEED_DIR = os.path.join(BASE_DIR, "seed")

# 与 App 端 M3UParser.isUsableUrl 保持一致：只收 http/https
USABLE_RE = re.compile(r"^(https?://)", re.IGNORECASE)

# 地址层面直接丢弃：点播视频文件、音频文件、带公众号推广参数的链接
BAD_URL_RE = re.compile(r"\.(mp4|mov|m4a|mp3)(\?|$)|公众号", re.IGNORECASE)


def usable_url(url: str) -> bool:
    return bool(USABLE_RE.match(url)) and not BAD_URL_RE.search(url)

# 明显不是频道名的垃圾行（辱骂、灌水、单字乱码等）
BAD_NAME_RE = re.compile(r"(盗源|狗|全家|下地狱|死全家|^#+$)")

# 按要求整组 / 整台剔除的频道名关键词（荔枝网、购物推广台一律不收）
DROP_NAME_WORDS = ["荔枝", "购物", "巡礼", "创一流"]

# 明显是分组名 / 占位文本泄漏成频道名的条目，直接丢弃
BLOCK_NAMES = {"广东移动", "广东联通", "移动网专用", "联通网专用", "电信网专用", "广东"}

# 央视别名 -> 规范名（沿用旧星海清单的对齐规则）
CW_ALIAS = {
    "央视综合": "CCTV1", "央视财经": "CCTV2", "央视综艺": "CCTV3",
    "央视中文国际": "CCTV4", "央视体育": "CCTV5", "央视电影": "CCTV6",
    "央视国防军事": "CCTV7", "央视电视剧": "CCTV8", "央视纪录": "CCTV9",
    "央视科教": "CCTV10", "央视戏曲": "CCTV11", "央视社会与法": "CCTV12",
    "央视新闻": "CCTV13", "央视少儿": "CCTV14", "央视音乐": "CCTV15",
    "央视奥林匹克": "CCTV16", "央视农业农村": "CCTV17",
    # 广东本地频道别名对齐，避免同一台在内网/备用分组里分裂成两张卡
    "广东珠江": "广东珠江频道",
    "珠江频道": "广东珠江频道",
    "广东大湾区卫视": "大湾区卫视",
    "大湾区卫视": "大湾区卫视",
}

GD_KW = ("广东", "广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆",
         "江门", "茂名", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞",
         "中山", "潮州", "揭阳", "云浮", "珠江", "南方", "大湾区", "岭南", "南海",
         "顺德", "嘉佳")

# 左侧分类顺序（App 端会再按自身权重排序，这里只决定同权重时的先后）
CAT_ORDER = ["广东", "央视", "卫视", "少儿", "纪实", "体育", "电影剧场",
             "综艺", "音乐", "教育", "地方", "香港", "澳门", "咪咕", "杂项"]

# 备用线路分组名：带“其他”关键字，让 App 端排序时沉到分类栏最底部
EXTRA_GROUP = "其他·备用线路"

# 台标库（fanmingming/live 的 tv 目录，清单见 seed/logos.txt）
LOGO_BASE = "https://raw.githubusercontent.com/fanmingming/live/main/tv"
LOGO_LIST_PATH = os.path.join(SEED_DIR, "logos.txt")

# 频道名 -> 台标文件名（库内文件名与频道名不一致时的对齐表；未命中不写台标）
LOGO_ALIAS = {
    "广东珠江频道": "广东珠江",
    "南方影视": "南方卫视",
    "中国教育1": "CETV1", "中国教育2": "CETV2",
    "中国教育3": "CETV3", "中国教育4": "CETV4",
    "卡酷动画": "卡酷少儿", "北京卡酷少儿": "卡酷少儿",
    "优漫卡通频道": "优漫卡通",
    "江苏城市频道": "江苏城市", "江苏影视频道": "江苏影视",
    "江苏教育": "江苏教育电视台", "江苏综艺频道": "江苏综艺",
    "公共新闻频道": "江苏公共新闻",
    "上视新闻综合": "上视新闻", "上视东方影视": "东方影视",
    "上海新闻综合": "上视新闻",
    "第一财经": "上海第一财经",
    "重庆影视剧": "重庆影视",
    "陕西体育休闲频道": "陕西体育休闲", "陕西新闻资讯频道": "陕西新闻资讯",
    "陕西都市青春频道": "陕西都市青春",
    "山东教育卫视": "山东教育",
    "中国农林卫视": "农林卫视",
    "书画频道": "书画", "国学频道": "国学",
    "海南广播电视总台少儿频道": "海南少儿",
    "海南广播电视总台文旅频道": "海南文旅",
    "佛山城市生活": "佛山公共",
}


LOGO_SET = set()


def load_logo_set():
    """读取台标库清单（fanmingming/live tv 目录文件名，不含扩展名）。"""
    global LOGO_SET
    if os.path.exists(LOGO_LIST_PATH):
        with open(LOGO_LIST_PATH, encoding="utf-8") as f:
            LOGO_SET = {ln.strip() for ln in f if ln.strip()}


def logo_for(name: str) -> str:
    """按频道名匹配台标库，返回 tvg-logo 地址；匹配不到返回空串（不写图标）。"""
    if not name:
        return ""
    base = LOGO_ALIAS.get(name)
    if not base and name in LOGO_SET:
        base = name
    if not base:
        stripped = re.sub(r"(频道|电视台)$", "", name)
        if stripped in LOGO_SET:
            base = stripped
    # 通用兜底：同系列/同省级台共用一张台标
    if not base:
        if re.match(r"^咪咕(视频|4K)", name):
            base = "咪咕视频"
        elif name.startswith("天津"):
            base = "天津卫视"
        elif name.startswith("湖北"):
            base = "湖北卫视"
        elif name.startswith("吉林"):
            base = "吉林卫视"
        elif "文化精品" in name:
            base = "文化精品"
        if base and base not in LOGO_SET:
            base = ""
    if not base:
        return ""
    return f"{LOGO_BASE}/{urllib.parse.quote(base)}.png"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_upstream_text(cfg: str) -> str:
    local = os.environ.get("SOURCE_FILE")
    if local:
        with open(local, "r", encoding="utf-8") as f:
            return f.read()
    last_err = None
    for url in [cfg["upstream"], cfg.get("upstream_fallback", "")]:
        if not url:
            continue
        try:
            return fetch_text(url)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[warn] 拉取失败 {url}: {e}")
    raise SystemExit(f"上游源全部拉取失败: {last_err}")


def clean_url(url: str) -> str:
    """去掉 URL 中误带的 # 片段（部分源把第二条线路用 # 拼在地址末尾）。"""
    return url.split("#", 1)[0].strip()


def keep_name(name: str) -> bool:
    if name.strip() in BLOCK_NAMES:
        return False
    return not any(w in name for w in DROP_NAME_WORDS)


def valid_name(name: str) -> bool:
    if not name or name.startswith("#"):
        return False
    if name.strip() in BLOCK_NAMES:
        return False
    if BAD_NAME_RE.search(name):
        return False
    if re.fullmatch(r"CCTV-?", name.strip(), re.I):
        return False
    # 分组名泄漏成频道名：如“广西移动”“广东联通”这类短地区 + 运营商后缀
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}(移动|联通|电信)", name.strip()):
        return False
    if len(name.strip()) == 1 and not re.search(r"[0-9a-z]", name.lower()):
        return False
    return bool(re.search(r"[0-9a-z\u4e00-\u9fff]", name.lower()))


QUALITY_RE = re.compile(
    r"((?:HD|4K|8K|超清|高清|标清|蓝光|SD|1080P|720P|超高清)\s*)+$", re.I)

# 高清/超高清画质标记（用于内网双版本线路排序）；命中即视为高清线
HD_RE = re.compile(r"高清|超清|4K|8K|HD|超高清|蓝光|1080P|720P", re.I)


def is_hd_name(name: str) -> bool:
    return bool(HD_RE.search(name or ""))


def norm(name: str) -> str:
    """频道名归一：别名对齐、CCTV 编号统一、剥画质后缀，用于跨源同名合并。"""
    if not name:
        return ""
    s = name.strip()
    for k, v in CW_ALIAS.items():
        if s.startswith(k):
            return v
    u = (s.upper().replace(" ", "").replace("-", "").replace("_", "")
         .replace("（", "(").replace("）", ")"))
    u = re.sub(r"\((HD|4K|8K|超清|高清|标清|蓝光|SD|1080P|720P)\)", "", u)
    u = QUALITY_RE.sub("", u)
    if re.search(r"CCTV[- ]?5\s*\+", u):
        return "CCTV5+"
    m = re.match(r"CCTV[- ]?(\d{1,2})", u)
    if m:
        return "CCTV%d" % int(m.group(1))
    if "CGTN" in u:
        return "CGTN"
    # 剥掉 “CCTV- / CCTV” 前缀，让 CCTV-风云足球 与 风云足球 合并
    u = re.sub(r"^CCTV[-—– ]?", "", u)
    s2 = re.sub(r"[（(].*?[)）]", "", s).strip()
    s2 = QUALITY_RE.sub("", s2).strip()
    s2 = re.sub(r"^CCTV[-—– ]?", "", s2)
    s2 = re.sub(r"^中央新影[-—– ]?", "", s2)
    # 尾部编号去前导零：熊猫频道01 -> 熊猫频道1
    s2 = re.sub(r"(\D)0(\d)$", r"\1\2", s2)
    return s2


def canon(name: str) -> str:
    return norm(name).lower()


def categorize(name: str, hint: str = "") -> str:
    """按频道性质归入左侧分类。顺序即判定优先级。"""
    n = QUALITY_RE.sub("", name.strip())
    if re.match(r"^CCTV\d", n) or n == "CGTN" or "CETV" in n.upper() \
            or "中国教育" in n or "央视" in n:
        return "央视"
    # 广东本地频道（含广东卫视/深圳卫视/大湾区卫视/珠江系/南方系）最优先归广东
    if any(k in n for k in GD_KW):
        return "广东"
    if "教育" in n:
        return "教育"
    if n.endswith("卫视"):
        return "卫视"
    if any(k in n for k in ("少儿", "卡通", "动画", "炫动", "动漫", "青少", "玩具", "幼", "中学生")):
        return "少儿"
    if any(k in n for k in ("体育", "赛事", "竞技", "电竞", "篮球", "足球", "网球",
                            "高尔夫", "台球", "搏击", "棋牌", "广场舞", "钓鱼",
                            "武术", "联赛", "体坛", "围棋", "垂钓")):
        return "体育"
    if any(k in n for k in ("纪录", "纪实", "地理", "新影", "老故事", "科技",
                            "兵器", "科教", "景观", "发现之旅", "熊猫频道")):
        return "纪实"
    # 电影频道放在地域判定前，避免“经典香港电影”这类被归进香港分组
    if any(k in n for k in ("剧场", "电影", "影视", "影院", "怀旧", "放映厅", "邵氏", "武侠", "喜剧", "经典")):
        return "电影剧场"
    if any(k in n for k in ("翡翠", "明珠", "凤凰", "TVB", "无线", "香港", "港台")):
        return "香港"
    if any(k in n for k in ("澳门", "澳视", "澳亚", "Macau")):
        return "澳门"
    if any(k in n for k in ("综艺", "娱乐", "秀场", "相声", "小品", "搞笑")):
        return "综艺"
    if any(k in n for k in ("音乐", "MTV", "电台", "DJ")):
        return "音乐"
    if "咪咕" in n:
        return "咪咕"
    if any(k in n for k in ("新闻", "都市", "城市", "生活", "乡村", "社会与法", "文旅",
                            "财经", "时尚", "汽车", "汽摩", "老年", "银龄", "戏曲",
                            "秦腔", "梨园", "文艺", "经视", "垄上", "红岩", "红叶",
                            "新农村", "自贸",
                            "国际", "指南", "天气", "特产", "旅游", "综合", "融媒", "资讯")):
        return "地方"
    if hint and hint in CAT_ORDER:
        return hint
    return "杂项"


# ---------- 多格式解析 ----------

def _logo_from_extinf(line: str) -> str:
    m = re.search(r'tvg-logo="([^"]*)"', line)
    if not m:
        m = re.search(r"tvg-logo=([^\s]+)", line)
    logo = m.group(1).strip() if m else ""
    return logo if usable_url(logo) else ""


def parse_m3u(text: str):
    """#EXTINF group-title / tvg-logo, 频道名 + 下一行为地址。"""
    rows = []
    pending = None
    pending_group = ""
    pending_logo = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF"):
            gm = re.search(r'group-title="([^"]*)"', line)
            pending_group = gm.group(1) if gm else ""
            pending_logo = _logo_from_extinf(line)
            comma = line.rfind(",")
            pending = line[comma + 1:].strip() if comma >= 0 else ""
            continue
        if line.startswith("#"):
            continue
        if pending and usable_url(line) and valid_name(pending):
            rows.append((pending, clean_url(line), pending_group, pending_logo))
            pending = None
    return rows


def parse_txt_genre(text: str):
    """分组,#genre# / 频道名,地址。"""
    rows = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "#genre#" in line:
            current = line.split(",", 1)[0].strip()
            continue
        comma = line.find(",")
        if comma <= 0:
            continue
        name, url = line[:comma].strip(), line[comma + 1:].strip()
        if usable_url(url) and valid_name(name):
            rows.append((name, clean_url(url), current, ""))
    return rows


def parse_seed(text: str):
    """分组#频道名#地址（星海静态清单格式）。"""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("#")
        if len(parts) >= 3:
            group, name, url = parts[0].strip(), parts[1].strip(), "#".join(parts[2:]).strip()
            if usable_url(url) and valid_name(name):
                rows.append((name, clean_url(url), group, ""))
    return rows


def parse_blank(text: str):
    """空行分段：##分组 / 频道名 / 地址 三行一组。"""
    rows = []
    current = ""
    pending = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            pending = None
            continue
        if line.startswith("##") or (line.startswith("#") and not line.startswith("#EXT")):
            current = line.lstrip("#").strip()
            pending = None
            continue
        if usable_url(line):
            if pending:
                rows.append((pending, clean_url(line), current, ""))
            pending = None
        else:
            pending = line
    return rows


def parse_any(text: str):
    """按格式特征自动选择解析器，返回 [(name, url, group, logo)]。"""
    if "#EXTINF" in text:
        return parse_m3u(text)
    if "#genre#" in text:
        return parse_txt_genre(text)
    # 种子格式：行内出现 `分组#频道名#http(s)://`（首段不含冒号，区别于 URL 片段）
    if re.search(r"^[^#\n:]+#[^#\n:]+#https?://", text, re.M):
        seed = parse_seed(text)
        if seed:
            return seed
    return parse_blank(text)


def parse_upstream_groups(text: str):
    """上游专用：返回 {分组: [(name, url)]} 与分组顺序。"""
    groups = {}
    order = []
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "#genre#" in line:
            current = line.split(",", 1)[0].strip()
            if current not in groups:
                groups[current] = []
                order.append(current)
            continue
        if current is None:
            continue
        comma = line.find(",")
        if comma <= 0:
            continue
        name, url = line[:comma].strip(), line[comma + 1:].strip()
        if usable_url(url) and valid_name(name) and keep_name(name):
            groups[current].append((name, url))
    return groups, order


# ---------- 合并模型 ----------

class ChannelBook:
    """按规范名合并频道：display 显示名 + urls 线路列表（首条为主线路）。"""

    def __init__(self):
        self.entries = {}
        self.order = []

    def add(self, name, url, logo="", internal=False):
        key = canon(name)
        if not key or not url:
            return
        if norm(name).strip() in BLOCK_NAMES:
            return
        if re.fullmatch(r"CCTV-?", norm(name), re.I):
            return
        meta = {"hd": is_hd_name(name), "internal": internal}
        if key in self.entries:
            if url not in self.entries[key]["urls"]:
                self.entries[key]["urls"].append(url)
                self.entries[key]["meta"][url] = meta
        else:
            display = norm(name)
            # 统一用台标库匹配，不采信第三方源自带的不可靠图标地址
            self.entries[key] = {
                "name": display,
                "urls": [url],
                "logo": logo_for(display),
                "meta": {url: meta},
            }
            self.order.append(key)

    def reorder_internal_hd(self):
        """内网线路内：高清线稳定排在标清线前面；外网/备用池线路仍沉在内网之后。"""
        for e in self.entries.values():
            meta = e["meta"]
            internal = [u for u in e["urls"] if meta[u]["internal"]]
            external = [u for u in e["urls"] if not meta[u]["internal"]]
            internal.sort(key=lambda u: 0 if meta[u]["hd"] else 1)
            e["urls"] = internal + external


# ---------- M3U 输出 ----------

def extinf_line(name: str, group: str, logo: str = "") -> str:
    logo_attr = f' tvg-logo="{logo}"' if logo else ""
    return f'#EXTINF:-1 tvg-name="{name}"{logo_attr} group-title="{group}",{name}'


def write_m3u(lines, rows, group_override=None):
    """rows: [(name, url, logo)]；group 缺省按频道名分类。"""
    by_cat = {}
    for name, url, logo in rows:
        cat = group_override or categorize(name)
        by_cat.setdefault(cat, []).append((name, url, logo))
    for cat in CAT_ORDER:
        items = by_cat.get(cat)
        if not items:
            continue
        for name, url, logo in items:
            lines.append(extinf_line(name, cat, logo))
            lines.append(url)
        lines.append("")


# ---------- 两类订阅构建 ----------

def apply_line_priority(book, priority):
    """按配置把指定频道的优先线路（主机/地址片段匹配）顶到第一条。

    未命中任何规则的频道保持原顺序；内网主线路仍在最前，除非规则显式指定替换。
    """
    if not priority:
        return
    for e in book.entries.values():
        rules = priority.get(e["name"])
        if not rules:
            continue
        for pat in rules:
            for i, u in enumerate(e["urls"]):
                if pat in u:
                    e["urls"].pop(i)
                    e["urls"].insert(0, u)
                    break


def build_subscription(sub_cfg, groups, spare_rows=None, spare_cap=8, priority=None):
    """移动 / 联通精简订阅：主线路分组 + 分类列表 + 统一备用线路。

    频道列表以内网主线路为准：每个规范名只在一个分类里占一条主卡片，
    内网地址固定为第 1 条线路；其余同名线路（上游备用分组 + 星海种子 +
    第三方直连）全部进入线路池，第 2 条及以后统一写入末尾备用线路分组。
    备用线路池里匹配不上列表频道的条目不新增卡片，直接丢弃；
    每台备用线路最多保留 spare_cap 条，避免单台堆积过多死线。
    """
    book = ChannelBook()
    primary_keys = []

    for slot in sub_cfg["groups"]:
        role = slot["role"]
        rows = []
        for src_group in slot["source_groups"]:
            rows.extend(groups.get(src_group, []))
            if not groups.get(src_group):
                print(f"[warn] 上游缺少分组「{src_group}」，已跳过")

        if role == "primary":
            for name, url in rows:
                k = canon(name)
                book.add(name, url, internal=True)
                if k in book.entries and k not in primary_keys:
                    primary_keys.append(k)
        else:
            for name, url in rows:
                book.add(name, url, internal=False)

    # 备用线路池：星海种子 + 第三方直连，只并入已存在的频道，不新增卡片
    spare_added = 0
    for name, url, _g, logo in spare_rows or []:
        k = canon(name)
        if k in book.entries:
            before = len(book.entries[k]["urls"])
            book.add(name, url, logo)
            if len(book.entries[k]["urls"]) > before:
                spare_added += 1
    if spare_rows:
        print(f"[ok] 备用线路池并入 {spare_added} 条匹配线路")

    # 内网双版本频道：高清线置顶，4:3 标清线沉到内网末尾（仅开启该规则的订阅）
    if sub_cfg.get("prefer_hd_internal"):
        book.reorder_internal_hd()

    # 指定频道的优先线路置顶（如珠江台改用 xch819、大湾区改用 20260809）
    apply_line_priority(book, priority)

    # 每台线路数量封顶：第 1 条主线路保留，备用线路按顺序截取
    for e in book.entries.values():
        if len(e["urls"]) > spare_cap + 1:
            e["urls"] = e["urls"][:spare_cap + 1]

    lines = ["#EXTM3U"]
    lines.append(f"# {sub_cfg['title']}")
    lines.append(f"# 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("# 规则: 分类列表每台一条主线路，其余线路见最底部备用线路分组")
    lines.append("")

    # 主列表：内网主线路优先，备用分组独有的频道排在后面
    ordered_keys = primary_keys + [k for k in book.order if k not in primary_keys]
    main_rows = [(book.entries[k]["name"], book.entries[k]["urls"][0],
                  book.entries[k]["logo"])
                 for k in ordered_keys]
    write_m3u(lines, main_rows)

    # 备用线路：第 2 条及以后，统一挂在沉底的备用线路分组
    extras = []
    for k in ordered_keys:
        e = book.entries[k]
        for u in e["urls"][1:]:
            extras.append((e["name"], u, e["logo"]))
    if extras:
        for name, url, logo in extras:
            lines.append(extinf_line(name, EXTRA_GROUP, logo))
            lines.append(url)
        lines.append("")

    stats = {"channels": len(book.entries), "lines": sum(len(e["urls"]) for e in book.entries.values())}
    return "\n".join(lines) + "\n", stats


def build_others(sub_cfg, groups, order):
    """全集备用模式：上游除 exclude_groups 外的分组原样保留。"""
    exclude = set(sub_cfg.get("exclude_groups", []))
    kept_groups = []
    channel_count = line_count = 0
    for g in order:
        if g in exclude:
            continue
        rows = groups.get(g, [])
        if not rows:
            continue
        seen = set()
        kept = []
        for name, url in rows:
            k = canon(name)
            if k in seen:
                continue
            seen.add(k)
            kept.append((name, url))
        kept_groups.append((g, kept))
        channel_count += len(kept)
        line_count += len(kept)

    lines = ["#EXTM3U"]
    lines.append(f"# {sub_cfg['title']}")
    lines.append(f"# 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    for g, kept in kept_groups:
        for name, url in kept:
            lines.append(extinf_line(name, g, logo_for(name)))
            lines.append(url)
        lines.append("")
    stats = {"channels": channel_count, "lines": line_count}
    return "\n".join(lines) + "\n", stats


def load_spare_pool(cfg):
    """备用线路池：本地星海种子 + 第三方直连源，返回 [(name, url, group, logo)]。

    这些源不单独成列表，只按频道名匹配并入已有频道的线路池；
    个别第三方源超时直接跳过，种子清单保证兜底。
    """
    pool_cfg = cfg.get("spare_pool", {})
    drop_words = pool_cfg.get("drop_words", [])
    rows = []

    seed_path = os.path.join(SEED_DIR, pool_cfg.get("seed_file", "xinghai.txt"))
    if os.path.exists(seed_path):
        seed_rows = parse_seed(open(seed_path, encoding="utf-8").read())
        for name, url, _g, logo in seed_rows:
            if keep_name(name) and not any(w in name for w in drop_words):
                rows.append((name, url, _g, logo))
        print(f"[ok] 备用池种子 {os.path.basename(seed_path)}: {len(seed_rows)} 行")
    else:
        print(f"[warn] 种子文件缺失: {seed_path}")

    for url in pool_cfg.get("third_party", []):
        try:
            text = fetch_text(url)
            third_rows = parse_any(text)
            for name, u, _hint, logo in third_rows:
                if any(w in name for w in drop_words) or not keep_name(name):
                    continue
                rows.append((name, u, _hint, logo))
            print(f"[ok] 备用池第三方源 {url[-32:]}: {len(third_rows)} 行")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 备用池第三方源拉取失败 {url[-32:]}: {type(e).__name__}")

    return rows


def main():
    cfg = load_config()
    load_logo_set()
    text = get_upstream_text(cfg)
    groups, order = parse_upstream_groups(text)
    spare_rows = load_spare_pool(cfg)
    spare_cap = int(cfg.get("spare_pool", {}).get("max_lines", 8))

    os.makedirs(OUT_DIR, exist_ok=True)
    for filename, sub_cfg in cfg["subscriptions"].items():
        mode = sub_cfg.get("mode")
        if mode == "others":
            content, stats = build_others(sub_cfg, groups, order)
        else:
            content, stats = build_subscription(sub_cfg, groups, spare_rows, spare_cap,
                                               sub_cfg.get("line_priority", {}))
        out_path = os.path.join(OUT_DIR, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[ok] {filename}: {stats['channels']} 个频道 / {stats['lines']} 条线路 -> {out_path}")

    print("完成。")


if __name__ == "__main__":
    main()
