#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py - LoL 下路 BP 助手 API 服务

本地开发启动:
  python3 app.py

主要接口:
  GET  /api/health
  GET  /api/champions          # 下路/辅助 英雄池
  GET  /api/champions/all      # 全部英雄（名单设置界面用）
  POST /api/recommend
  GET  /api/mylists            # 4 份个人名单
  POST /api/mylists            # 增删改名单（add / remove / set / remove_unknown）
  GET  /api/counter/<champion>
  GET  /api/lcu/state        # 客户端实时状态（只读，供自动填充使用）
  POST /api/lcu/config       # 开关自动识别
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, render_template, request

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:
    Style = None
    lazy_pinyin = None

import lcu
from bp_engine import (
    VALID_KEYS,
    extract_stat,
    find_counter_picks,
    new_bp_state,
    run_recommend,
)
from champion_aliases import CHAMPION_ALIASES
from my_lists import (
    LIST_FILES,
    LIST_LABELS,
    LIST_OPPOSITE,
    LIST_ROLES,
    get_lists,
    remove_unknown_line,
    save_list,
    update_list,
)
from scraper.chinese_getchampion.hero_id_mapping import HERO_ID_MAPPING

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "botlane_dataset.json")
CN_NAMES_PATH = os.path.join(BASE_DIR, "scraper", "chinese_getchampion", "英雄名字.txt")

app = Flask(__name__)
DB = None
CHAMPION_META = None

# ── LCU 监听（只读） ─────────────────────────────────────────────
# 后台线程轮询英雄选择状态，只用于自动填充输入框。
# 只发 GET 请求：不 pick、不 ban、不点击、不修改任何游戏状态。
# 想彻底关掉：设置环境变量 LCU_DISABLED=1，或页面上点开关。
LCU_WATCHER = lcu.WATCHER
_lcu_start_lock = threading.Lock()
_lcu_started = False


def ensure_lcu_started():
    """惰性启动后台监听线程（首次请求或启动时触发）。"""
    global _lcu_started
    if _lcu_started or os.environ.get("LCU_DISABLED") == "1":
        return
    with _lcu_start_lock:
        if not _lcu_started:
            LCU_WATCHER.start()
            _lcu_started = True

BP_SLOT_LANES = {
    "ally_ad": "bottom",
    "enemy_ad": "bottom",
    "ally_sup": "support",
    "enemy_sup": "support",
}

BP_SLOT_LABELS = {
    "ally_ad": "己方 ADC",
    "enemy_ad": "敌方 ADC",
    "ally_sup": "己方辅助",
    "enemy_sup": "敌方辅助",
}


def has_chinese(text):
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def token_value(value, token_type, label=None):
    value = str(value).strip().lower()
    if not value:
        return None
    return {
        "value": value,
        "compact": "".join(value.split()),
        "type": token_type,
        "label": label or value,
    }


def add_token(tokens, seen, value, token_type, label=None):
    token = token_value(value, token_type, label)
    if not token:
        return
    key = (token["value"], token["type"])
    if key in seen:
        return
    seen.add(key)
    tokens.append(token)


def pinyin_tokens(text):
    if not lazy_pinyin or not Style or not has_chinese(text):
        return []
    syllables = [item for item in lazy_pinyin(text, errors="ignore") if item]
    initials = [
        item for item in lazy_pinyin(text, style=Style.FIRST_LETTER, errors="ignore") if item
    ]
    if not syllables:
        return []
    values = [
        ("".join(syllables), "pinyin", text),
        (" ".join(syllables), "pinyin", text),
    ]
    if initials:
        values.append(("".join(initials), "initials", text))
    return values


def build_search_tokens(cn_name, key, champion_id, aliases):
    tokens = []
    seen = set()
    add_token(tokens, seen, cn_name, "cn_name", cn_name)
    add_token(tokens, seen, key, "id", key)
    add_token(tokens, seen, key.title(), "english", key.title())
    add_token(tokens, seen, champion_id, "champion_id", str(champion_id))
    for alias in aliases:
        add_token(tokens, seen, alias, "alias", alias)
    for source in [cn_name, *aliases]:
        for value, token_type, label in pinyin_tokens(source):
            add_token(tokens, seen, value, token_type, label)
    return tokens


def has_chinese(text):
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def token_value(value, token_type, label=None):
    value = str(value).strip().lower()
    if not value:
        return None
    return {
        "value": value,
        "compact": "".join(value.split()),
        "type": token_type,
        "label": label or value,
    }


def add_token(tokens, seen, value, token_type, label=None):
    token = token_value(value, token_type, label)
    if not token:
        return
    key = (token["value"], token["type"])
    if key in seen:
        return
    seen.add(key)
    tokens.append(token)


def pinyin_tokens(text):
    if not lazy_pinyin or not Style or not has_chinese(text):
        return []
    syllables = [item for item in lazy_pinyin(text, errors="ignore") if item]
    initials = [
        item for item in lazy_pinyin(text, style=Style.FIRST_LETTER, errors="ignore") if item
    ]
    if not syllables:
        return []
    values = [
        ("".join(syllables), "pinyin", text),
        (" ".join(syllables), "pinyin", text),
    ]
    if initials:
        values.append(("".join(initials), "initials", text))
    return values


def build_search_tokens(cn_name, key, champion_id, aliases):
    tokens = []
    seen = set()
    add_token(tokens, seen, cn_name, "cn_name", cn_name)
    add_token(tokens, seen, key, "id", key)
    add_token(tokens, seen, key.title(), "english", key.title())
    add_token(tokens, seen, champion_id, "champion_id", str(champion_id))
    for alias in aliases:
        add_token(tokens, seen, alias, "alias", alias)
    for source in [cn_name, *aliases]:
        for value, token_type, label in pinyin_tokens(source):
            add_token(tokens, seen, value, token_type, label)
    return tokens


def load_db():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            "找不到 data/botlane_dataset.json，请先运行 python3 pre_fetch.py"
        )
    with open(DB_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def get_db():
    """按需加载数据库；数据文件被 update_data.py 更新后自动重载（不用重启服务）。"""
    global DB
    try:
        mtime = os.path.getmtime(DB_PATH)
    except OSError:
        mtime = None
    if DB is None or (mtime is not None and mtime != get_db.last_mtime):
        DB = load_db()
        get_db.last_mtime = mtime
    return DB

get_db.last_mtime = None


def load_champion_meta():
    cn_names = []
    if os.path.exists(CN_NAMES_PATH):
        with open(CN_NAMES_PATH, "r", encoding="utf-8") as file:
            cn_names = [line.strip() for line in file if line.strip()]

    meta = {}
    for (key, champion_id), cn_name in zip(HERO_ID_MAPPING.items(), cn_names):
        aliases = CHAMPION_ALIASES.get(key, [])
        search_tokens = build_search_tokens(cn_name, key, champion_id, aliases)
        search_text = " ".join(token["value"] for token in search_tokens).lower()
        meta[key] = {
            "id": key,
            "name": key.title(),
            "cn_name": cn_name,
            "aliases": aliases,
            "champion_id": champion_id,
            "avatar": f"/static/avatars/{champion_id}.png",
            "search_tokens": search_tokens,
            "search_text": search_text,
        }
    return meta


def get_champion_meta():
    global CHAMPION_META
    if CHAMPION_META is None:
        CHAMPION_META = load_champion_meta()
    return CHAMPION_META


def enrich_champion(champion_id, fallback_tier=None):
    meta = get_champion_meta().get(champion_id, {})
    return {
        "id": champion_id,
        "name": meta.get("name", champion_id.title()),
        "cn_name": meta.get("cn_name", champion_id.title()),
        "aliases": meta.get("aliases", []),
        "champion_id": meta.get("champion_id"),
        "tier": fallback_tier,
        "avatar": meta.get("avatar", f"/static/avatars/{champion_id}.png"),
        "search_tokens": meta.get("search_tokens", []),
        "search_text": meta.get("search_text", champion_id),
    }


def enrich_recommendation_rows(rows):
    for row in rows:
        meta = enrich_champion(row["name"], row.get("tier"))
        row["display_name"] = meta["cn_name"]
        row["english_name"] = meta["name"]
        row["champion_id"] = meta["champion_id"]
        row["avatar"] = meta["avatar"]
    return rows


def build_bp_display(bp_state):
    labels = {
        "ally_ad": "己方 ADC",
        "ally_sup": "己方辅助",
        "enemy_ad": "敌方 ADC",
        "enemy_sup": "敌方辅助",
    }
    display = {}
    for key, value in bp_state.items():
        champion = enrich_champion(value) if value else None
        display[key] = {
            "label": labels[key],
            "id": value,
            "display_name": champion["cn_name"] if champion else "未知",
            "avatar": champion["avatar"] if champion else None,
        }
    return display


def build_result_summary(results):
    confidence_counts = {"high": 0, "medium": 0, "low": 0, "very_low": 0}
    for row in results:
        level = row.get("confidence_level")
        if level in confidence_counts:
            confidence_counts[level] += 1
    return {
        "total": len(results),
        "confidence_counts": confidence_counts,
        "complete_data_count": confidence_counts["high"],
    }


def build_score_rows(score_map, db, lane=None, top_n=20):
    rows = []
    for champion_id, raw_value in score_map.items():
        tier = None
        if lane:
            tier = db["tiers"].get(lane, {}).get(champion_id)
        if tier == "?":
            continue
        stat = extract_stat(raw_value, legacy_games=300)
        row = {
            "name": champion_id,
            "tier": tier,
            "win_rate": round(stat["winrate"] * 100, 2) if stat["winrate"] else 0,
            "games": int(stat["games"]),
        }
        rows.append(row)
    rows.sort(key=lambda item: item["win_rate"], reverse=True)
    return enrich_recommendation_rows(rows[:top_n])


def api_error(message, status_code=400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status_code


def normalize_top_n(value, default=10, minimum=1, maximum=50):
    if value is None:
        return default
    if str(value).strip().lower() == "all":
        return None
    try:
        top_n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, top_n))


def build_mylists_payload():
    meta = get_champion_meta()
    lists = get_lists()
    payload = {"ok": True, "lists": {}}
    for key in LIST_FILES:
        entry = lists[key]
        champions = []
        for champion_id in entry["ids"]:
            info = meta.get(champion_id, {})
            champions.append(
                {
                    "id": champion_id,
                    "cn_name": info.get("cn_name") or champion_id.title(),
                    "name": info.get("name") or champion_id.title(),
                    "avatar": info.get("avatar"),
                }
            )
        payload["lists"][key] = {
            "label": LIST_LABELS[key],
            "role": LIST_ROLES.get(key, ""),
            "opposite": LIST_OPPOSITE.get(key, ""),
            "file": entry["file"],
            "rel_file": os.path.relpath(entry["file"], BASE_DIR).replace("\\", "/"),
            "champions": champions,
            "unknown": entry["unknown"],
        }
    return payload


def apply_my_lists(role, result, top_n):
    """按角色应用个人名单：不推荐的英雄剔除且不占名额，常用英雄打标"""
    lists = get_lists()
    if role == "adc":
        block_key, fav_key = "adc_block", "adc_fav"
    else:
        block_key, fav_key = "support_block", "support_fav"
    blocked_ids = set(lists[block_key]["ids"])
    favorite_ids = set(lists[fav_key]["ids"])

    all_rows = [row for row in result["results"] if row["name"] not in blocked_ids]
    for row in all_rows:
        if row["name"] in favorite_ids:
            row["is_favorite"] = True

    result["results"] = all_rows if top_n is None else all_rows[:top_n]
    result["precise_results"] = sorted(
        all_rows,
        key=lambda item: item.get("precision_score", item["final_rating"]),
        reverse=True,
    )[:7]
    result["my_lists"] = {
        "blocked": sorted(blocked_ids),
        "favorites": sorted(favorite_ids),
    }
    return result


def validate_bp_state(db, bp_state):
    invalid_fields = []
    for key, champion in bp_state.items():
        if not champion:
            continue
        lane = BP_SLOT_LANES[key]
        tier = db.get("tiers", {}).get(lane, {}).get(champion)
        if tier and tier != "?":
            continue
        invalid_fields.append(
            {
                "field": key,
                "label": BP_SLOT_LABELS[key],
                "value": champion,
                "expected_lane": lane,
            }
        )
    return invalid_fields


def build_champion_list(db, lane):
    champions = []
    for name, tier in db["tiers"].get(lane, {}).items():
        if tier == "?":
            continue
        champion = enrich_champion(name, tier)
        stat = extract_stat(db.get("hero_stats", {}).get(lane, {}).get(name), legacy_games=0)
        champion["win_rate"] = round(stat["winrate"] * 100, 2) if stat["winrate"] else 0
        champion["games"] = int(stat["games"])
        champions.append(champion)
    return champions


@app.get("/api/mylists")
def mylists():
    return jsonify(build_mylists_payload())


@app.post("/api/mylists")
def mylists_update():
    payload = request.get_json(silent=True) or {}
    list_key = str(payload.get("list", "")).strip()
    action = str(payload.get("action", "")).strip().lower()
    champion = str(payload.get("champion", "")).strip()

    if list_key not in LIST_FILES:
        return api_error("list 必须是 " + "、".join(LIST_FILES))
    if action not in ("add", "remove", "set", "remove_unknown"):
        return api_error("action 必须是 add / remove / set / remove_unknown")

    # set：整体覆盖一份名单（传空数组即清空），champions 里可以是 中文名/别名/英文key/数字ID
    if action == "set":
        champions = payload.get("champions", [])
        if champions is None:
            champions = []
        if not isinstance(champions, list):
            return api_error("champions 必须是数组")
        try:
            save_list(list_key, [str(item) for item in champions])
        except ValueError as exc:
            return api_error(str(exc))
        return jsonify(build_mylists_payload())

    # remove_unknown：删掉文件里一行识别不了的内容
    if action == "remove_unknown":
        if not champion:
            return api_error("champion 不能为空")
        try:
            remove_unknown_line(list_key, champion)
        except ValueError as exc:
            return api_error(str(exc))
        return jsonify(build_mylists_payload())

    if not champion:
        return api_error("champion 不能为空")

    try:
        update_list(list_key, champion, add=(action == "add"))
    except ValueError as exc:
        return api_error(str(exc))
    return jsonify(build_mylists_payload())


@app.get("/api/champions/all")
def all_champions():
    """全部英雄（含非下路/辅助英雄），供名单设置界面点选。"""
    meta = get_champion_meta()
    if lazy_pinyin:
        def sort_key(item):
            return "".join(lazy_pinyin(item["cn_name"] or item["name"]))
    else:
        def sort_key(item):
            return item["cn_name"] or item["name"]
    champions = sorted(meta.values(), key=sort_key)
    return jsonify(
        {
            "ok": True,
            "champions": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "cn_name": item["cn_name"],
                    "aliases": item["aliases"],
                    "champion_id": item["champion_id"],
                    "avatar": item["avatar"],
                    "search_tokens": item["search_tokens"],
                    "search_text": item["search_text"],
                }
                for item in champions
            ],
        }
    )


@app.get("/api/lcu/state")
def lcu_state():
    """客户端实时状态 + 自动填充数据（只读）。

    返回的英雄对象格式和 /api/champions 一致，前端可以直接填进输入框。
    """
    ensure_lcu_started()
    snapshot = LCU_WATCHER.snapshot()
    session = snapshot.get("session") or {}

    def champion_of(key):
        if not key:
            return None
        return enrich_champion(key)

    ally = {
        "adc": champion_of((session.get("ally") or {}).get("adc")),
        "support": champion_of((session.get("ally") or {}).get("support")),
    }

    enemy_session = session.get("enemy") or {}
    enemy = {}
    for slot in ("adc", "support"):
        item = enemy_session.get(slot) or {}
        enemy[slot] = {
            "champion": champion_of(item.get("key")),
            "confidence": item.get("confidence"),
            "inferred": True,
        }

    in_champ_select = bool(snapshot.get("in_champ_select"))
    return jsonify({
        "ok": True,
        "enabled": snapshot.get("enabled", False),
        "running": snapshot.get("running", False),
        "connected": bool(snapshot.get("connected")),
        "source": snapshot.get("source"),
        "error": snapshot.get("error"),
        "in_champ_select": in_champ_select,
        "revision": snapshot.get("revision", 0),
        "last_poll": snapshot.get("last_poll"),
        "queue": {
            "id": session.get("queue_id"),
            "name": session.get("queue_name"),
        } if in_champ_select else None,
        "phase": session.get("phase"),
        "timer": session.get("timer"),
        "my_position": session.get("my_position"),
        "role_hint": session.get("my_slot"),
        "ally": ally if in_champ_select else {"adc": None, "support": None},
        "enemy": enemy if in_champ_select else {
            "adc": {"champion": None, "confidence": None},
            "support": {"champion": None, "confidence": None},
        },
        "bans": session.get("bans"),
        "enemy_pick_count": session.get("enemy_pick_count", 0),
    })


@app.post("/api/lcu/config")
def lcu_config():
    """开关自动识别（关掉后完全不轮询客户端）。"""
    payload = request.get_json(silent=True) or {}
    if "enabled" in payload:
        LCU_WATCHER.set_enabled(bool(payload["enabled"]))
    if payload.get("enabled"):
        ensure_lcu_started()
    return jsonify({"ok": True, "enabled": LCU_WATCHER.is_enabled()})


@app.get("/api/health")
def health():
    db = get_db()
    return jsonify(
        {
            "ok": True,
            "service": "lol-botlane-bp",
            "data_meta": db.get("meta", {}),
        }
    )


# ────────────────────── 数据更新（网页内触发） ──────────────────────
#
# 跑的是跟 update_bp_data.bat 同一个 update_data.py，只是改成后台线程执行，
# 并把子进程的输出实时抓出来给前端显示进度。

UPDATE_LOCK = threading.Lock()

# pre_fetch.py 的 progress() 输出形如：
#   [████████░░░░░░] 16% (8/50) jinx/bottom
PROGRESS_RE = re.compile(r"\[[^\]]*\]\s*(\d+)%\s*\((\d+)/(\d+)\)\s*(.*)")
# 阶段标记 [1/3] [2/3] [3/3] → 各占总进度的区间
STAGE_SPAN = {1: (5, 40), 2: (40, 85), 3: (85, 94)}

UPDATE_STATE = {
    "running": False,
    "done": False,
    "ok": None,
    "phase": "idle",   # idle/backup/fetch/validate/test/done/failed
    "label": "",
    "percent": 0,
    "logs": [],
    "error": None,
    "started_at": None,
    "finished_at": None,
}


def _log(line):
    line = line.rstrip()
    if not line:
        return
    with UPDATE_LOCK:
        UPDATE_STATE["logs"].append(line)
        UPDATE_STATE["logs"] = UPDATE_STATE["logs"][-40:]
        UPDATE_STATE["label"] = line


def _mark(**changes):
    with UPDATE_LOCK:
        UPDATE_STATE.update(changes)


def _handle_output(line):
    """解析一行输出，更新阶段和百分比。"""
    stage = re.search(r"\[(\d)/3\]", line)
    if stage:
        num = int(stage.group(1))
        start, _end = STAGE_SPAN.get(num, (5, 40))
        names = {1: "梯队数据", 2: "协同与克制矩阵", 3: "写入数据文件"}
        _mark(phase="fetch", percent=start, label=f"[{num}/3] {names.get(num, '')}...")

    match = PROGRESS_RE.search(line)
    if match:
        pct = int(match.group(1))
        # 找出当前处于哪个阶段，把 pct 映射到该阶段的区间里
        with UPDATE_LOCK:
            label = UPDATE_STATE.get("label", "")
        stage = re.search(r"\[(\d)/3\]", label) or re.search(r"\[(\d)/3\]", "")
        cur = int(stage.group(1)) if stage else 2
        start, end = STAGE_SPAN.get(cur, (40, 85))
        _mark(percent=start + (end - start) * pct / 100.0)
        return

    if "已备份旧数据" in line:
        _mark(phase="backup", percent=4)
    elif "数据校验通过" in line:
        _mark(phase="validate", percent=95)
    elif "test_api" in line:
        _mark(phase="test", percent=97)
    elif "数据更新完成" in line:
        _mark(phase="done", percent=100)


# 日志里哪些行算"真正说明失败原因"的（traceback 的最后几行基本都命中）
ERROR_HINTS = (
    "Error", "Traceback", "Exception", "失败", "错误",
    "refused", "timed out", "timeout", "denied",
)


def _extract_error(logs, code):
    """从日志里挑出说明"为什么失败"的行，别只丢一个退出码给用户。

    update_data.py 崩溃时 traceback 会打到 stderr，我们把它一起收进 logs 了，
    所以扫一遍就能拿到真正的异常，而不是干巴巴的 "退出码 1"。
    """
    picks = [ln.strip() for ln in logs if any(h in ln for h in ERROR_HINTS)]
    if picks:
        return " ｜ ".join(picks[-3:])
    return f"更新进程退出码 {code}（旧数据已自动恢复，详情看日志）"


def _run_update(with_timeline=False):
    """后台线程：跑 update_data.py，边跑边把输出喂给 UPDATE_STATE。"""
    _mark(running=True, done=False, ok=None, error=None, phase="backup",
          percent=2, logs=[], label="正在启动...",
          started_at=time.strftime("%H:%M:%S"), finished_at=None)

    args = [sys.executable, "-u", "update_data.py"]
    if with_timeline:
        args.append("--with-timeline")
    # PYTHONUNBUFFERED= 让输出不缓冲，进度才能实时读到；
    # PYTHONIOENCODING=utf-8 很关键：从 bat/cmd 启动时子进程继承 GBK 代码页，
    # pre_fetch 标题里的 🚀 编不出来会直接 UnicodeEncodeError 崩掉（退出码 1）。
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")

    try:
        proc = subprocess.Popen(
            args, cwd=BASE_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        _mark(running=False, done=True, ok=False, phase="failed",
              error=f"无法启动更新进程：{exc}", finished_at=time.strftime("%H:%M:%S"))
        return

    buf = ""
    try:
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            for ch in chunk.decode("utf-8", errors="replace"):
                if ch in ("\r", "\n"):
                    if buf.strip():
                        _log(buf)
                        _handle_output(buf)
                    buf = ""
                else:
                    buf += ch
        if buf.strip():
            _log(buf)
            _handle_output(buf)
        proc.wait()
        code = proc.returncode
    except Exception as exc:
        _mark(running=False, done=True, ok=False, phase="failed",
              error=f"更新过程异常：{exc}", finished_at=time.strftime("%H:%M:%S"))
        return

    if code == 0:
        # 数据集换了，清掉依赖它的缓存，让下次请求重新加载
        try:
            lcu.invalidate_role_cache()
        except Exception:
            pass
        try:
            db = get_db()
            update_time = (db.get("meta") or {}).get("update_time") or "-"
        except Exception:
            update_time = "-"
        _mark(running=False, done=True, ok=True, phase="done", percent=100,
              label=f"更新完成，数据时间 {update_time}",
              finished_at=time.strftime("%H:%M:%S"))
    else:
        with UPDATE_LOCK:
            logs = list(UPDATE_STATE["logs"])
        _mark(running=False, done=True, ok=False, phase="failed",
              error=_extract_error(logs, code),
              finished_at=time.strftime("%H:%M:%S"))


@app.post("/api/data/update")
def data_update():
    """启动一次数据更新。已在运行时不会重复启动。"""
    payload = request.get_json(silent=True) or {}
    with UPDATE_LOCK:
        if UPDATE_STATE["running"]:
            return jsonify({"ok": False, "started": False,
                            "reason": "更新已在运行中"})
    thread = threading.Thread(
        target=_run_update,
        kwargs={"with_timeline": bool(payload.get("with_timeline"))},
        name="data-update", daemon=True,
    )
    thread.start()
    return jsonify({"ok": True, "started": True})


@app.get("/api/data/update/status")
def data_update_status():
    """查询更新进度（前端轮询这个）。"""
    with UPDATE_LOCK:
        snapshot = {
            key: (list(value) if isinstance(value, list) else value)
            for key, value in UPDATE_STATE.items()
        }
    snapshot["ok"] = True
    return jsonify(snapshot)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/champions")
def champions():
    db = get_db()
    return jsonify(
        {
            "ok": True,
            "data_meta": db.get("meta", {}),
            "bottom": build_champion_list(db, "bottom"),
            "support": build_champion_list(db, "support"),
        }
    )


@app.post("/api/recommend")
def recommend():
    db = get_db()
    payload = request.get_json(silent=True) or {}

    role = str(payload.get("role", "")).strip().lower()
    if role not in ("support", "adc"):
        return api_error("role 必须是 support 或 adc")

    raw_bp_state = payload.get("bp_state") or {}
    if not isinstance(raw_bp_state, dict):
        return api_error("bp_state 必须是对象")

    bp_state = new_bp_state()
    for key in VALID_KEYS:
        value = raw_bp_state.get(key)
        bp_state[key] = str(value).strip().lower() if value else None

    invalid_fields = validate_bp_state(db, bp_state)
    if invalid_fields:
        labels = [
            f"{item['label']}={item['value']}"
            for item in invalid_fields
        ]
        return api_error(
            "BP 槽位包含无效英雄或位置不匹配: " + "，".join(labels),
            invalid_fields=invalid_fields,
        )

    top_n = normalize_top_n(payload.get("top_n"))
    # 先取完整排行，再用个人名单过滤，保证不推荐的英雄不占用推荐名额
    result = run_recommend(role, bp_state, db, top_n=None)
    apply_my_lists(role, result, top_n)
    enrich_recommendation_rows(result["results"])
    enrich_recommendation_rows(result.get("precise_results", []))
    result["bp_display"] = build_bp_display(result["bp_state"])
    result["summary"] = build_result_summary(result["results"])
    result["ok"] = True
    return jsonify(result)


@app.get("/api/counter/<champion>")
def counter(champion):
    db = get_db()
    top_n = normalize_top_n(request.args.get("top_n"), default=5)
    champion = champion.strip().lower()
    if not champion:
        return api_error("champion 不能为空")

    return jsonify(
        {
            "ok": True,
            "champion": champion,
            "data_meta": db.get("meta", {}),
            "adc": enrich_recommendation_rows(
                find_counter_picks(champion, "adc", db, top_n=top_n)
            ),
            "support": enrich_recommendation_rows(
                find_counter_picks(champion, "support", db, top_n=top_n)
            ),
        }
    )


@app.get("/api/synergy/<champion>")
def synergy(champion):
    db = get_db()
    top_n = normalize_top_n(request.args.get("top_n"), default=20)
    champion = champion.strip().lower()
    if not champion:
        return api_error("champion 不能为空")

    rows = []
    for partner, raw_value in db["synergy"].get(champion, {}).items():
        lane = "bottom" if partner in db["tiers"].get("bottom", {}) else "support"
        tier = db["tiers"].get(lane, {}).get(partner)
        if tier == "?":
            continue
        stat = extract_stat(raw_value, legacy_games=300)
        rows.append(
            {
                "name": partner,
                "tier": tier,
                "win_rate": round(stat["winrate"] * 100, 2) if stat["winrate"] else 0,
                "games": int(stat["games"]),
            }
        )
    rows.sort(key=lambda item: item["win_rate"], reverse=True)

    return jsonify(
        {
            "ok": True,
            "champion": enrich_champion(champion),
            "data_meta": db.get("meta", {}),
            "results": enrich_recommendation_rows(rows[:top_n]),
        }
    )


@app.get("/api/matchup/<champion>")
def matchup(champion):
    db = get_db()
    top_n = normalize_top_n(request.args.get("top_n"), default=20)
    champion = champion.strip().lower()
    if not champion:
        return api_error("champion 不能为空")

    data = db["counter"].get(champion, {})
    return jsonify(
        {
            "ok": True,
            "champion": enrich_champion(champion),
            "data_meta": db.get("meta", {}),
            "vs_adc": build_score_rows(
                data.get("vs_adc", {}), db, lane="bottom", top_n=top_n
            ),
            "vs_support": build_score_rows(
                data.get("vs_sup", {}), db, lane="support", top_n=top_n
            ),
        }
    )


@app.get("/api/tier/<lane>")
def tier(lane):
    db = get_db()
    lane = lane.strip().lower()
    if lane == "adc":
        lane = "bottom"
    if lane not in ("bottom", "support"):
        return api_error("lane 必须是 bottom/adc 或 support")

    return jsonify(
        {
            "ok": True,
            "lane": lane,
            "data_meta": db.get("meta", {}),
            "results": build_champion_list(db, lane),
        }
    )


if __name__ == "__main__":
    get_db()
    ensure_lcu_started()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    app.run(host=host, port=port, debug=False, use_reloader=False)
