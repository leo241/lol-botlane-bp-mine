#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
my_lists.py - 个人自定义名单（不推荐 / 经常使用）

名单文件位于 data/lists/ 下，直接用记事本就能编辑：
  adc_blocklist.txt      下路(ADC) 不推荐名单 —— 名单内英雄不参与推荐、不占推荐名额
  adc_favorites.txt      下路(ADC) 经常使用名单 —— 被推荐时页面会显眼标记
  support_blocklist.txt  辅助 不推荐名单
  support_favorites.txt  辅助 经常使用名单

每行一个英雄，以下写法都能识别（大小写随意、自动忽略空格）：
  凯特琳        （中文名 / 常用别名，比如 女警 也可以）
  皮城女警      （称号）
  Caitlyn      （英文名）
  caitlyn      （小写 key）
  51           （英雄数字 ID）

以 # 开头的行是注释，空行忽略。
写错的行不会导致报错，只会在 /api/mylists 的 unknown 里提示，方便排查。

改完名单文件立即生效，不需要重启服务。

除了用记事本改，网页上的「名单设置」按钮也能可视化编辑这 4 个文件：
勾选/搜索英雄即可增删，改动会立刻写回对应的 txt。
"""

import os
import threading

from champion_aliases import CHAMPION_ALIASES
from scraper.chinese_getchampion.hero_id_mapping import HERO_ID_MAPPING

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LISTS_DIR = os.path.join(BASE_DIR, "data", "lists")

LIST_FILES = {
    "adc_block": "adc_blocklist.txt",
    "adc_fav": "adc_favorites.txt",
    "support_block": "support_blocklist.txt",
    "support_fav": "support_favorites.txt",
}

LIST_LABELS = {
    "adc_block": "下路(ADC) 不推荐名单",
    "adc_fav": "下路(ADC) 经常使用名单",
    "support_block": "辅助 不推荐名单",
    "support_fav": "辅助 经常使用名单",
}

# 每个名单属于哪个分路（前端用来做冲突提示/默认打开）
LIST_ROLES = {
    "adc_block": "adc",
    "adc_fav": "adc",
    "support_block": "support",
    "support_fav": "support",
}

# 同一个分路里的另一份名单（常用 <-> 不推荐），用来提示"两边都写了"
LIST_OPPOSITE = {
    "adc_block": "adc_fav",
    "adc_fav": "adc_block",
    "support_block": "support_fav",
    "support_fav": "support_block",
}

_lock = threading.RLock()
_cache = {"stamp": None, "data": None}


def _build_name_index():
    """生成 名称/别名/称号/数字ID -> 英雄小写key 的索引"""
    index = {}
    for key, champion_id in HERO_ID_MAPPING.items():
        entries = [key, key.title(), str(champion_id)]
        entries.extend(CHAMPION_ALIASES.get(key, []))
        for entry in entries:
            normalized = str(entry).strip().lower().replace(" ", "")
            if normalized and normalized not in index:
                index[normalized] = key
    return index


_NAME_INDEX = _build_name_index()

_CN_NAMES = None


def _load_cn_names():
    """英雄小写key -> 中文名（和页面上显示的保持一致），读不到就返回空字符串"""
    global _CN_NAMES
    if _CN_NAMES is not None:
        return _CN_NAMES
    names = []
    path = os.path.join(BASE_DIR, "scraper", "chinese_getchampion", "英雄名字.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            names = [line.strip() for line in file if line.strip()]
    mapping = {}
    for index, key in enumerate(HERO_ID_MAPPING):
        if index < len(names):
            mapping[key] = names[index]
    _CN_NAMES = mapping
    return mapping


def display_name(champion_id):
    """写回文件时用的名字：优先中文名，其次常用别名，最后是英文 key"""
    candidates = [_load_cn_names().get(champion_id)]
    candidates.extend(CHAMPION_ALIASES.get(champion_id, []))
    for candidate in candidates:
        # 只有确认这个名字能被反查回同一个英雄，才写进文件
        if candidate and resolve_name(candidate) == champion_id:
            return candidate
    return champion_id


def resolve_name(raw):
    """把任意写法（中文/英文/key/ID）解析成英雄小写 key，认不出返回 None"""
    if raw is None:
        return None
    normalized = str(raw).strip().lower().replace(" ", "")
    if not normalized:
        return None
    return _NAME_INDEX.get(normalized)


def _read_list_file(path):
    entries = []   # [{"raw": 原始行, "id": 英雄key}]
    unknown = []   # [{"raw": 原始行, "line": 行号}]
    if not os.path.exists(path):
        return entries, unknown
    with open(path, "r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            champion_id = resolve_name(stripped)
            if champion_id is None:
                unknown.append({"raw": stripped, "line": line_no})
            else:
                entries.append({"raw": stripped, "id": champion_id})
    return entries, unknown


def _stamp():
    stamp = []
    for key in sorted(LIST_FILES):
        path = os.path.join(LISTS_DIR, LIST_FILES[key])
        try:
            stamp.append((path, os.path.getmtime(path)))
        except OSError:
            stamp.append((path, None))
    return tuple(stamp)


def get_lists(force=False):
    """读取 4 个名单；文件有改动会自动重载（不用重启服务）"""
    stamp = _stamp()
    with _lock:
        if not force and _cache["data"] is not None and _cache["stamp"] == stamp:
            return _cache["data"]
        data = {}
        for key, filename in LIST_FILES.items():
            path = os.path.join(LISTS_DIR, filename)
            entries, unknown = _read_list_file(path)
            seen = set()
            ids = []
            for entry in entries:
                if entry["id"] not in seen:
                    seen.add(entry["id"])
                    ids.append(entry["id"])
            data[key] = {"ids": ids, "unknown": unknown, "file": path}
        _cache["stamp"] = stamp
        _cache["data"] = data
        return data


def update_list(list_key, champion_name, add=True):
    """把一个英雄写入 / 移出名单文件；保留原有注释行，移除时保留未识别行"""
    if list_key not in LIST_FILES:
        raise ValueError(f"未知名单: {list_key}")
    champion_id = resolve_name(champion_name)
    if champion_id is None:
        raise ValueError(f"无法识别英雄: {champion_name}")
    path = os.path.join(LISTS_DIR, LIST_FILES[list_key])
    os.makedirs(LISTS_DIR, exist_ok=True)

    with _lock:
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                lines = file.readlines()

        kept = []
        removed = False
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and resolve_name(stripped) == champion_id:
                removed = True
                continue
            kept.append(line)

        if add:
            if kept and not kept[-1].endswith("\n"):
                kept[-1] += "\n"
            kept.append(display_name(champion_id) + "\n")
        elif not removed:
            # 本来就不在名单里，不动文件
            get_lists(force=True)
            return champion_id

        with open(path, "w", encoding="utf-8") as file:
            file.writelines(kept)

        get_lists(force=True)
    return champion_id


def _split_file_lines(lines):
    """把文件拆成 注释行 / 已识别行(id -> 原始写法) / 未识别行"""
    comments = []
    raw_by_id = {}
    unknown = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            comments.append(line if line.endswith("\n") else line + "\n")
            continue
        champion_id = resolve_name(stripped)
        if champion_id is None:
            unknown.append(line if line.endswith("\n") else line + "\n")
        elif champion_id not in raw_by_id:
            raw_by_id[champion_id] = stripped
    return comments, raw_by_id, unknown


def save_list(list_key, champion_ids):
    """整体覆盖一份名单（顺序即传入顺序）。

    保留文件里的注释、未识别行，以及老条目的原始写法（用户手打的中文名不会被改成英文 key）。
    """
    if list_key not in LIST_FILES:
        raise ValueError(f"未知名单: {list_key}")
    path = os.path.join(LISTS_DIR, LIST_FILES[list_key])
    os.makedirs(LISTS_DIR, exist_ok=True)

    with _lock:
        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as file:
                lines = file.readlines()

        comments, raw_by_id, unknown = _split_file_lines(lines)

        output = list(comments)
        seen = set()
        for raw in champion_ids:
            champion_id = resolve_name(raw)
            if champion_id is None or champion_id in seen:
                continue
            seen.add(champion_id)
            output.append((raw_by_id.get(champion_id) or display_name(champion_id)) + "\n")
        output.extend(unknown)

        with open(path, "w", encoding="utf-8") as file:
            file.writelines(output)

        get_lists(force=True)
    return sorted(seen)


def remove_unknown_line(list_key, raw):
    """删掉一行识别不了的内容（比如手打错的英雄名）"""
    if list_key not in LIST_FILES:
        raise ValueError(f"未知名单: {list_key}")
    target = str(raw or "").strip()
    if not target:
        raise ValueError("raw 不能为空")
    path = os.path.join(LISTS_DIR, LIST_FILES[list_key])
    if not os.path.exists(path):
        return False

    with _lock:
        with open(path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        kept = []
        removed = False
        for line in lines:
            stripped = line.strip()
            if (
                not removed
                and stripped
                and not stripped.startswith("#")
                and stripped == target
                and resolve_name(stripped) is None
            ):
                removed = True
                continue
            kept.append(line)

        if removed:
            with open(path, "w", encoding="utf-8") as file:
                file.writelines(kept)
            get_lists(force=True)
    return removed
