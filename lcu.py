#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCU（League Client Update）只读接入模块。

设计原则 —— 安全第一：
  * 只发 GET 请求，绝不调用任何 pick / ban / 自动点击 / 修改状态的接口。
  * 不读游戏进程内存，不注入，不 hook。
  * 轮询间隔 >= 1.5s（默认 2s），属于"礼貌级别"的读取频率。
  * 所有异常都被吞掉并转成状态字符串，任何情况下都不能影响网页本身的功能。

功能：
  1. 自动发现客户端（lockfile 优先，PowerShell/wmic/psutil 兜底）
  2. 解析英雄选择 session（双方 pick / ban / 位置 / 倒计时 / 队列）
  3. 推断敌方谁是 ADC、谁是辅助（LCU 不公开敌方位置，只能靠英雄本身判断）
  4. 后台线程轮询，把状态放进线程安全的快照供 Flask 读取

环境变量（都用于调试或关停，正常使用不需要）：
  LCU_DISABLED=1          完全关闭 LCU 功能
  LCU_PORT / LCU_TOKEN    直接指定端口和令牌（跳过自动探测）
  LCU_LOCKFILE            指定 lockfile 路径（测试用）
  LCU_INTERVAL            轮询间隔秒数，最小 1.5
"""

import base64
import json
import os
import re
import subprocess
import threading
import time

import requests

try:  # 可选依赖，装了就用，没装也不影响
    import psutil
except ImportError:
    psutil = None

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


# ──────────────────────────── 队列 / 常量 ────────────────────────────

QUEUE_NAMES = {
    400: "普通征召",
    420: "单双排位",
    430: "匹配模式",
    440: "灵活排位",
    450: "极地大乱斗",
    490: "快速匹配",
    700: "斗魂竞技场",
    720: "克隆大作战",
    1700: "斗魂竞技场",
}

# 只在下路相关的队列里做自动填充（其他模式没有下路概念）
BOTLANE_QUEUES = {400, 420, 430, 440, 490}

# 常见的国服/外服 lockfile 位置
LOCKFILE_PATHS = [
    r"D:\WeGame\英雄联盟\lockfile",
    r"C:\WeGame\英雄联盟\lockfile",
    r"E:\WeGame\英雄联盟\lockfile",
    r"D:\英雄联盟\lockfile",
    r"E:\英雄联盟\lockfile",
    r"C:\英雄联盟\lockfile",
    r"C:\Program Files\WeGame\英雄联盟\lockfile",
    r"C:\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    r"E:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\League of Legends\lockfile",
]

PROCESS_NAMES = (
    "leagueclientux.exe",
    "leagueclient.exe",
    "league of legends.exe",
    "riotclientservices.exe",
)


# ──────────────────────────── 客户端探测 ────────────────────────────


def _parse_lockfile_content(content):
    """lockfile 内容格式：进程名:pid:端口:令牌:协议"""
    parts = (content or "").strip().split(":")
    if len(parts) >= 4:
        return parts[2], parts[3]
    return None, None


def _iter_lockfiles():
    """遍历可能的 lockfile 位置（含环境变量指定的）。"""
    seen = set()

    override = os.environ.get("LCU_LOCKFILE")
    if override:
        candidates = [override]
    else:
        candidates = list(LOCKFILE_PATHS)
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        for base, suffix in [
            (local, r"Riot Games\League of Legends\lockfile"),
            (local, r"Tencent\League of Legends\lockfile"),
            (program_files, "League of Legends\\lockfile"),
            (program_files_x86, "League of Legends\\lockfile"),
        ]:
            if base:
                candidates.append(os.path.join(base, suffix))

    for path in candidates:
        if path and path not in seen:
            seen.add(path)
            yield path


def _scan_processes_commandline():
    """不依赖第三方库扫描进程命令行，返回 [(port, token, 来源)]。

    优先 PowerShell（Win10/11 都在），wmic 作为老系统兜底，装了 psutil 就一起用。
    """
    found = []

    def _extract(cmdline):
        match_port = re.search(r"--app-port=(\d+)", cmdline)
        match_token = re.search(r"--remoting-auth-token=([\w-]+)", cmdline)
        if match_port and match_token:
            found.append((match_port.group(1), match_token.group(1), "process-cmdline"))

    # 1) PowerShell CIM（Win 8+ 全支持，不依赖 wmic 是否被移除）
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe' "
            "or Name='LeagueClient.exe' or Name='RiotClientServices.exe'\" "
            "| Select-Object -ExpandProperty CommandLine"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in (result.stdout or "").splitlines():
            _extract(line)
    except Exception:
        pass

    # 2) wmic（老系统兜底）
    if not found:
        try:
            result = subprocess.run(
                ["cmd", "/c", "wmic", "PROCESS", "GET", "name,commandline"],
                capture_output=True, text=True, timeout=8,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in (result.stdout or "").splitlines():
                if "app-port" in line:
                    _extract(line)
        except Exception:
            pass

    # 3) psutil（装了就用，最准）
    if not found and psutil is not None:
        try:
            for proc in psutil.process_iter(["name", "cmdline"]):
                if (proc.info.get("name") or "").lower() in PROCESS_NAMES:
                    _extract(" ".join(proc.info.get("cmdline") or []))
        except Exception:
            pass

    return found


def _is_game_client(port, token):
    """确认这个端口是游戏客户端（而不是启动器），避免连到 Riot Client。"""
    try:
        auth = base64.b64encode(f"riot:{token}".encode()).decode()
        resp = requests.get(
            f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
            verify=False, timeout=3,
        )
        return resp.status_code == 200
    except Exception:
        return False


def find_lcu_process():
    """找到 LCU 端口和令牌，返回 (port, token, 来源)；找不到返回 (None, None, None)。"""
    env_port = os.environ.get("LCU_PORT")
    env_token = os.environ.get("LCU_TOKEN")
    if env_port and env_token:
        return env_port, env_token, "env"

    candidates = []

    for path in _iter_lockfiles():
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as file:
                    port, token = _parse_lockfile_content(file.read())
                if port and token:
                    candidates.append((port, token, f"lockfile:{path}"))
        except Exception:
            continue

    candidates.extend(_scan_processes_commandline())

    # 去重
    seen = set()
    unique = []
    for port, token, source in candidates:
        key = (port, token)
        if key not in seen:
            seen.add(key)
            unique.append((port, token, source))

    for port, token, source in unique:
        if _is_game_client(port, token):
            return port, token, source

    if unique:
        return unique[0]

    return None, None, None


# ──────────────────────────── 位置归一化 ────────────────────────────


def normalize_position(position):
    """LCU 的位置名 → 本项目内部名。"""
    if not position:
        return ""
    position = str(position).lower()
    if position == "bottom":
        return "adc"
    if position == "utility":
        return "support"
    if position in ("top", "jungle", "middle", "mid"):
        return "middle" if position == "middle" else position
    return position


# ──────────────────────────── 角色推断 ────────────────────────────
#
# LCU 只公开"我方"的 assignedPosition，敌方的位置是隐藏的。
# 所以敌方谁是 ADC、谁是辅助，只能根据英雄本身来判断。
# 数据基础：data/botlane_dataset.json 的 hero_stats.bottom / hero_stats.support
# 里的 games 场次。
#
# 为什么不用 tiers 的 S+/S/S- 评级？因为那个评级是"这英雄在这路上打得怎么样"，
# 不是"这英雄是不是打这路的"。实战反例：
#   nidalee 在 support 评级 S（但只有 390 场 —— 黑科技，不是真辅助）
#   yasuo   在 bottom 评级 S（2497 场，其实人家主打中单）
# 只有场次能说明"归属"，所以下面一律用 games 分级。
#
# 对于两边场次都不少的摇摆英雄，用下面的经验表补一刀（权重低于场次）。

# 两边都上榜时，实际更常见的位置倾向
LEAN_OVERRIDE = {
    # 偏 ADC
    "ashe": "adc", "ezreal": "adc", "missfortune": "adc", "twitch": "adc",
    "ziggs": "adc", "mel": "adc",
    # 偏辅助
    "brand": "support", "heimerdinger": "support", "hwei": "support",
    "senna": "support", "seraphine": "support", "swain": "support",
    "teemo": "support", "veigar": "support", "velkoz": "support",
    "xerath": "support", "aurelionsol": "support", "syndra": "support",
    "taliyah": "support", "twistedfate": "support",
}

_ROLE_CACHE = None


def invalidate_role_cache():
    """数据更新后调用：botlane_dataset.json 换了新的，分级缓存必须失效。

    不清理的话，网页上点完"更新数据"后仍然按旧版本的场次排名做判断。
    """
    global _ROLE_CACHE
    _ROLE_CACHE = None


def _load_role_sets():
    """读出下路 / 辅助的分级表（带缓存），返回 ({key: 0~3}, {key: 0~3})。

    分级依据是**位置内百分位**，不是绝对场次。见 _rank_tiers 的说明。
    """
    global _ROLE_CACHE
    if _ROLE_CACHE is not None:
        return _ROLE_CACHE

    raw = {"bottom": {}, "support": {}}
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "data", "botlane_dataset.json")
    try:
        with open(path, "r", encoding="utf-8") as file:
            db = json.load(file)
        stats = db.get("hero_stats", {})
        for lane in ("bottom", "support"):
            for key, item in (stats.get(lane) or {}).items():
                try:
                    raw[lane][str(key).lower()] = int(item.get("games") or 0)
                except (TypeError, ValueError):
                    raw[lane][str(key).lower()] = 0
    except Exception:
        pass

    _ROLE_CACHE = (_rank_tiers(raw["bottom"]), _rank_tiers(raw["support"]))
    return _ROLE_CACHE


def _pct_tier(percentile):
    """百分位 → 分级 0~3。分越高越说明是这条路的主力。"""
    if percentile >= 85:
        return 3
    if percentile >= 65:
        return 2
    if percentile >= 35:
        return 1
    return 0


def _rank_tiers(games_map):
    """把 {英雄: 场次} 转成 {英雄: 0~3 分级}。

    关键：用**位置内百分位**，不用绝对场次。
    因为 Lolalytics 的场次会随版本进度整体放大 —— 版本初刚抓完数据时
    全服才几万场，版本末能到几十万场。用绝对场次定档会两头不讨好：
      · 版本初期：真主力（索拉卡、娜美）掉到 0 分，功能等于关掉
      · 版本末期：亚索下路(2497)、豹女辅助(390) 这种客串混成 3 分主力
    百分位只看"在这条路上排前百分之几"，跟数据总量无关，也跟榜单
    收录了多少英雄无关（按名次归一化），所以跨版本、跨位置都稳定。
    """
    if not games_map:
        return {}
    values = sorted(games_map.values())
    total = len(values)
    return {
        key: _pct_tier(sum(1 for g in values if g <= games) / total * 100.0)
        for key, games in games_map.items()
    }


def score_lanes(champion_key):
    """给一个英雄打"像 ADC"和"像辅助"的分，返回 (adc_score, support_score)。

    分数来自它在下路 / 辅助里的**百分位排名**，不是有没有上榜、也不是绝对场次。
    于是：卡莎 = 3（下路第 1），亚索 = 1（下路第 21/50），豹女 = 0（辅助垫底）。
    客串的黑科技不会再来冒充主力，而且换版本也不会失效。
    """
    if not champion_key:
        return 0, 0
    key = champion_key.lower()
    bottom, support = _load_role_sets()

    adc = bottom.get(key, 0)
    sup = support.get(key, 0)

    # 摇摆英雄的人工倾向：只 +1，权重压在排名之下。
    # （原来是 +2，会把亚索这种客串的直接顶成 ADC）
    lean = LEAN_OVERRIDE.get(key)
    if lean == "adc":
        adc += 1
    elif lean == "support":
        sup += 1

    return adc, sup


def infer_botlane_roles(picks):
    """从一批英雄里挑出 ADC 和辅助。

    picks: [{"champion_id": int, "key": str}]（key 可能是 None，表示识别不了的新英雄）
    返回: {"adc": (key, confidence), "support": (key, confidence)}
    confidence: high / medium / low；key 为 None 表示"没把握，不填"

    三条硬规矩（针对"对面先出几个非下路英雄就被硬塞进槽位"的问题）：
      1. 一个英雄在下路/辅助都没什么场次 → 它基本是上中野，直接踢出候选池。
      2. ADC 槽只收"像 ADC"的，辅助槽只收"像辅助"的，不为了填满而硬凑。
      3. 置信度 low 的一律不填（留空，前端显示"待定"）。
    """
    usable = [p for p in picks if p.get("key")]
    result = {"adc": (None, None), "support": (None, None)}
    if not usable:
        return result

    scored = []
    for pick in usable:
        adc_score, sup_score = score_lanes(pick["key"])
        scored.append({
            "key": pick["key"],
            "champion_id": pick.get("champion_id"),
            "adc": adc_score,
            "sup": sup_score,
        })

    # ① 完全没有下路信号的（上单 / 中单 / 打野）直接踢掉。
    #    旧实现是 "known if known else scored" —— 没人认识就硬拿全 0 分的凑数，
    #    这正是"亚索/劫/盲僧被填进下路"的根源。
    candidates = [item for item in scored if item["adc"] + item["sup"] > 0]
    if not candidates:
        return result

    # ② 槽位资格：想占 ADC 槽至少要有点 ADC 样子，辅助槽同理
    adc_pool = [item for item in candidates if item["adc"] > 0]
    sup_pool = [item for item in candidates if item["sup"] > 0]

    # ③ 就出了一两个人的时候：信号不够强就别猜。
    #    比如对面只出了个亚索（下路 2497 场 = 1 分）—— 明显说明不了他就是 ADC。
    if len(candidates) == 1:
        item = candidates[0]
        if item["adc"] >= 2 and item["adc"] > item["sup"]:
            result["adc"] = (item["key"], _confidence(item, "adc"))
        elif item["sup"] >= 2 and item["sup"] > item["adc"]:
            result["support"] = (item["key"], _confidence(item, "support"))
        return result

    # ④ 多人：在"合格的 ADC"和"合格的辅助"之间做最优配对
    best = None
    for adc_item in adc_pool:
        for sup_item in sup_pool:
            if adc_item["key"] == sup_item["key"]:
                continue
            total = adc_item["adc"] + sup_item["sup"]
            # 同分时，选"分工更明确"的一对（各自的绝对分差更大）
            tie = abs(adc_item["adc"] - adc_item["sup"]) + abs(sup_item["sup"] - sup_item["adc"])
            if best is None or (total, tie) > (best[0], best[1]):
                best = (total, tie, adc_item, sup_item)

    if best is None:
        # 只有一边有合格的人（比如出了俩 ADC 倾向的），就只填那一边，
        # 绝不拿另一个去硬凑辅助位。
        pool, slot = (adc_pool, "adc") if adc_pool else (sup_pool, "support")
        if pool:
            top = max(pool, key=lambda item: item[slot])
            if top[slot] >= 2:
                result[slot] = (top["key"], _confidence(top, slot))
        return result

    _, _, adc_item, sup_item = best

    # ⑤ 门槛：置信度 low 就不填，交给前端显示"待定"
    adc_conf = _confidence(adc_item, "adc")
    sup_conf = _confidence(sup_item, "support")
    if adc_conf != "low":
        result["adc"] = (adc_item["key"], adc_conf)
    if sup_conf != "low":
        result["support"] = (sup_item["key"], sup_conf)
    return result


def _confidence(item, slot):
    """置信度：这个英雄有多明确地指向该位置。

    high   = 明确（卡莎 → ADC、锤石 → 辅助）
    medium = 大致靠谱（德莱文 → ADC）
    low    = 说不准（亚索下路 1 分、两边场次都稀少的摇摆英雄）→ 不填
    """
    own = item["adc"] if slot == "adc" else item["sup"]
    other = item["sup"] if slot == "adc" else item["adc"]
    diff = own - other
    if own >= 2 and diff >= 2:
        return "high"
    if own >= 2 and diff >= 1:
        return "medium"
    if own >= 1 and diff >= 1:
        return "medium"
    return "low"


# ──────────────────────────── session 解析 ────────────────────────────


def flatten_actions(raw_actions):
    flat = []
    for group in raw_actions or []:
        if isinstance(group, list):
            flat.extend(group)
    return flat


def _champion_key(id_to_key, champion_id):
    """把 LCU 的数字英雄 ID 转成项目内部 key（兼容 int / str 两种键）。"""
    if not champion_id:
        return None
    if champion_id in id_to_key:
        return id_to_key[champion_id]
    return id_to_key.get(str(champion_id))


def parse_session(session, id_to_key=None):
    """解析英雄选择 session，输出本项目需要的信息。"""
    id_to_key = id_to_key or {}
    my_team = session.get("myTeam") or []
    their_team = session.get("theirTeam") or []
    local_cell = session.get("localPlayerCellId", -1)
    my_team_cells = {player.get("cellId") for player in my_team}

    def _pick(player, team):
        champion_id = player.get("championId") or 0
        return {
            "champion_id": champion_id,
            "key": _champion_key(id_to_key, champion_id),
            "position": normalize_position(player.get("assignedPosition")),
            "cell": player.get("cellId"),
            "team": team,
        }

    def _prepick(player):
        intent = player.get("championPickIntent") or 0
        if not intent:
            return None
        return {
            "champion_id": intent,
            "key": _champion_key(id_to_key, intent),
            "position": normalize_position(player.get("assignedPosition")),
        }

    my_picks = [_pick(p, "ally") for p in my_team if (p.get("championId") or 0)]
    enemy_picks = [_pick(p, "enemy") for p in their_team if (p.get("championId") or 0)]
    my_intents = [x for x in (_prepick(p) for p in my_team) if x]
    enemy_intents = [x for x in (_prepick(p) for p in their_team) if x]

    # ── 我方：位置是公开的，直接按位置取 ──
    ally = {"adc": None, "support": None}
    for pick in my_picks:
        if pick["position"] == "adc" and not ally["adc"]:
            ally["adc"] = pick["key"]
        elif pick["position"] == "support" and not ally["support"]:
            ally["support"] = pick["key"]

    # 我方还没锁定的话，用预选（悬停）补一下
    for intent in my_intents:
        key = intent["key"]
        if not key:
            continue
        position = intent["position"]
        if position == "adc" and not ally["adc"]:
            ally["adc"] = key
        elif position == "support" and not ally["support"]:
            ally["support"] = key
        else:
            adc_score, sup_score = score_lanes(key)
            if adc_score > sup_score and not ally["adc"]:
                ally["adc"] = key
            elif sup_score > adc_score and not ally["support"]:
                ally["support"] = key

    # ── 敌方：位置隐藏，靠英雄推断 ──
    enemy_inferred = infer_botlane_roles(enemy_picks)
    enemy = {
        "adc": {"key": enemy_inferred["adc"][0], "confidence": enemy_inferred["adc"][1]},
        "support": {"key": enemy_inferred["support"][0], "confidence": enemy_inferred["support"][1]},
    }

    # 我方自己的位置
    my_position = ""
    for player in my_team:
        if player.get("cellId") == local_cell:
            my_position = normalize_position(player.get("assignedPosition"))

    # ban
    my_bans, enemy_bans = [], []
    for action in flatten_actions(session.get("actions")):
        if action.get("type") == "ban" and action.get("completed") and (action.get("championId") or 0):
            key = _champion_key(id_to_key, action.get("championId"))
            if action.get("actorCellId") in my_team_cells:
                my_bans.append(key or action["championId"])
            else:
                enemy_bans.append(key or action["championId"])

    timer_info = session.get("timer") or {}
    phase = timer_info.get("phase", "BAN_PICK")
    total_sec = (timer_info.get("totalTime") or 0) / 1000.0
    left_ms = timer_info.get("adjustedTimeLeftInPhase")
    if left_ms is None:
        left_ms = total_sec * 1000
    remaining_sec = left_ms / 1000.0

    # 我在这局里是哪个位置（决定网页该推荐 ADC 还是辅助）
    my_slot = my_position if my_position in ("adc", "support") else None

    queue_id = session.get("queueId") or 0
    return {
        "queue_id": queue_id,
        "queue_name": QUEUE_NAMES.get(queue_id, f"未知队列({queue_id})" if queue_id else "未知队列"),
        "phase": phase,
        "timer": {
            "phase": phase,
            "total_sec": int(total_sec),
            "remaining_sec": max(0, int(remaining_sec)),
        },
        "my_position": my_position,
        "my_slot": my_slot,
        "my_picks": my_picks,
        "enemy_picks": enemy_picks,
        "ally": ally,
        "enemy": enemy,
        "bans": {"ally": my_bans, "enemy": enemy_bans},
        "enemy_pick_count": len(enemy_picks),
    }


def has_players(session):
    """确认 session 是真的在选人（而不是空壳）。"""
    if not isinstance(session, dict):
        return False
    if session.get("myTeam") or session.get("theirTeam"):
        return True
    return bool(flatten_actions(session.get("actions")))


# ──────────────────────────── 后台轮询 ────────────────────────────


class LcuWatcher:
    """后台线程轮询 LCU，把最新状态放进线程安全快照。"""

    def __init__(self, interval=None):
        self.interval = max(1.5, float(interval or os.environ.get("LCU_INTERVAL") or 2.0))
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._session_key_cache = {}
        self._state = {
            "enabled": os.environ.get("LCU_DISABLED") != "1",
            "running": False,
            "connected": False,
            "source": None,
            "error": None,
            "in_champ_select": False,
            "session": None,
            "revision": 0,
            "last_poll": None,
            "last_change": None,
            "poll_count": 0,
        }

    # ── 生命周期 ──

    def start(self):
        if os.environ.get("LCU_DISABLED") == "1":
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lcu-watcher", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ── 对外接口 ──

    def is_enabled(self):
        with self._lock:
            return bool(self._state["enabled"])

    def set_enabled(self, enabled):
        with self._lock:
            self._state["enabled"] = bool(enabled)
            if not enabled:
                self._state["connected"] = False
                self._state["in_champ_select"] = False
                self._state["session"] = None
                self._state["error"] = None

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self._state, default=str))

    # ── 内部实现 ──

    def _publish(self, **changes):
        with self._lock:
            changed = {k: v for k, v in changes.items() if self._state.get(k) != v}
            self._state.update(changes)
            if changed:
                self._state["revision"] += 1
                self._state["last_change"] = time.strftime("%H:%M:%S")

    def _loop(self):
        self._publish(running=True)
        client = None  # (port, token, source)
        headers = None
        base_url = None
        fail_count = 0

        while not self._stop.is_set():
            if not self.is_enabled():
                client = None
                headers = None
                time.sleep(1.0)
                continue

            if client is None:
                port, token, source = find_lcu_process()
                if not port:
                    self._publish(connected=False, source=None, error=None,
                                  in_champ_select=False, session=None)
                    self._stop.wait(3.0)
                    continue
                auth = base64.b64encode(f"riot:{token}".encode()).decode()
                headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
                base_url = f"https://127.0.0.1:{port}"
                client = (port, token, source)
                self._publish(connected=True, source=source, error=None)

            try:
                resp = requests.get(
                    f"{base_url}/lol-champ-select/v1/session",
                    headers=headers, verify=False, timeout=3,
                )
            except Exception as error:
                fail_count += 1
                self._publish(connected=False, error=f"连接失败：{type(error).__name__}")
                if fail_count >= 2:
                    client = None  # 客户端可能关了/换端口，重新探测
                    fail_count = 0
                    self._stop.wait(1.0)
                continue

            fail_count = 0
            self._publish(connected=True, error=None, last_poll=time.strftime("%H:%M:%S"),
                          poll_count=self._state["poll_count"] + 1)

            if resp.status_code == 200:
                try:
                    session = resp.json()
                except Exception:
                    session = None
                if session and has_players(session):
                    parsed = parse_session(session, self._id_to_key())
                    self._publish(in_champ_select=True, session=parsed)
                else:
                    self._publish(in_champ_select=False, session=None)
            else:
                # 404 = 目前不在英雄选择
                self._publish(in_champ_select=False, session=None)

            self._stop.wait(self.interval)

    def _id_to_key(self):
        """数字 ID → 项目内部英雄 key（英雄 ID 是固定的，缓存一次即可）。"""
        if not self._session_key_cache:
            try:
                from scraper.chinese_getchampion.hero_id_mapping import HERO_ID_MAPPING
                self._session_key_cache = {str(cid): key for key, cid in HERO_ID_MAPPING.items()}
            except Exception:
                self._session_key_cache = {}
        return self._session_key_cache


# 全局单例（app.py 用）
WATCHER = LcuWatcher()
