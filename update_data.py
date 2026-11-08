#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全数据更新脚本。

常用命令:
  python3 update_data.py                 # 运行 pre_fetch.py 更新数据
  python3 update_data.py --with-timeline # 额外抓取时间趋势
  python3 update_data.py --check-only    # 只校验当前数据和 API

策略:
  1. 更新前备份旧数据
  2. pre_fetch.py 写临时文件并原子替换正式数据
  3. 校验新数据结构和覆盖率
  4. 运行 API 冒烟测试
  5. 任一步失败则恢复旧数据
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

FROZEN = getattr(sys, "frozen", False)


def _resolve_base_dir():
    # 冻结态（exe）：资源统一放在 exe 旁的 lolbp_utils/；开发态用脚本所在目录。
    if FROZEN:
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "lolbp_utils")
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _resolve_base_dir()
DATA_PATH = os.path.join(BASE_DIR, "data", "botlane_dataset.json")
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
VERSIONS_DIR = os.path.join(BASE_DIR, "data", "versions")
MANIFEST_PATH = os.path.join(VERSIONS_DIR, "manifest.json")
MIN_BOTTOM_CHAMPIONS = 25
MIN_SUPPORT_CHAMPIONS = 35
MIN_HERO_STATS_RATIO = 0.9
MIN_SYNERGY_ROWS = 10
MIN_COUNTER_ADC_ROWS = 50
MIN_COUNTER_SUP_ROWS = 30
MAX_FETCH_ERROR_RATIO = 0.25


def run_command(args):
    print(f"\n$ {' '.join(args)}")
    return subprocess.run(args, cwd=BASE_DIR, check=True)


def validate_dataset(path=DATA_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据库不存在: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    for key in [
        "meta",
        "tiers",
        "hero_stats",
        "synergy",
        "counter",
        "synergy_by_lane",
        "counter_by_lane",
    ]:
        if key not in data:
            raise ValueError(f"数据库缺少字段: {key}")

    tiers = data["tiers"]
    bottom_count = sum(
        1 for tier in tiers.get("bottom", {}).values() if tier and tier != "?"
    )
    support_count = sum(
        1 for tier in tiers.get("support", {}).values() if tier and tier != "?"
    )
    if bottom_count < MIN_BOTTOM_CHAMPIONS or support_count < MIN_SUPPORT_CHAMPIONS:
        raise ValueError(
            f"梯队数据过少: bottom={bottom_count}, support={support_count}"
        )

    hero_stats = data["hero_stats"]
    bottom_stats_count = len(hero_stats.get("bottom", {}))
    support_stats_count = len(hero_stats.get("support", {}))
    bottom_stats_ratio = bottom_stats_count / bottom_count if bottom_count else 0
    support_stats_ratio = support_stats_count / support_count if support_count else 0
    if (
        bottom_stats_ratio < MIN_HERO_STATS_RATIO
        or support_stats_ratio < MIN_HERO_STATS_RATIO
    ):
        raise ValueError(
            "基础英雄数据覆盖不足: "
            f"bottom={bottom_stats_count}/{bottom_count}, "
            f"support={support_stats_count}/{support_count}"
        )

    synergy_rows = sum(len(value) for value in data["synergy"].values())
    counter_adc_rows = sum(
        len(value.get("vs_adc", {})) for value in data["counter"].values()
    )
    counter_sup_rows = sum(
        len(value.get("vs_sup", {})) for value in data["counter"].values()
    )
    if (
        synergy_rows < MIN_SYNERGY_ROWS
        or counter_adc_rows < MIN_COUNTER_ADC_ROWS
        or counter_sup_rows < MIN_COUNTER_SUP_ROWS
    ):
        raise ValueError(
            "协同/克制数据覆盖不足: "
            f"synergy={synergy_rows}, "
            f"counter_adc={counter_adc_rows}, "
            f"counter_sup={counter_sup_rows}"
        )

    for lane in ("bottom", "support"):
        if lane not in data["synergy_by_lane"] or lane not in data["counter_by_lane"]:
            raise ValueError(f"按位置矩阵缺少 lane: {lane}")
        if not data["synergy_by_lane"][lane] or not data["counter_by_lane"][lane]:
            raise ValueError(f"按位置矩阵为空: {lane}")

    meta = data.get("meta", {})
    fetch_errors_count = int(meta.get("fetch_errors_count") or 0)
    coverage = meta.get("coverage") or {}
    fetch_attempts = int(coverage.get("fetch_attempts") or 0)
    if fetch_attempts and fetch_errors_count / fetch_attempts > MAX_FETCH_ERROR_RATIO:
        raise ValueError(
            "抓取失败比例过高: "
            f"errors={fetch_errors_count}, attempts={fetch_attempts}"
        )

    print(
        "数据校验通过: "
        f"bottom={bottom_count}, support={support_count}, "
        f"hero_stats={bottom_stats_count + support_stats_count}, "
        f"synergy={synergy_rows}, "
        f"counter_adc={counter_adc_rows}, "
        f"counter_sup={counter_sup_rows}, "
        f"fetch_errors={fetch_errors_count}"
    )
    return data


def backup_dataset():
    if not os.path.exists(DATA_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"botlane_dataset.{stamp}.json")
    shutil.copy2(DATA_PATH, backup_path)
    print(f"已备份旧数据: {backup_path}")
    return backup_path


def restore_backup(backup_path):
    if not backup_path:
        return
    shutil.copy2(backup_path, DATA_PATH)
    print(f"已恢复旧数据: {backup_path}")


def run_api_tests():
    if FROZEN:
        # 冻结态没有独立的 test_api.py 可跑，直接在本进程内执行冒烟测试
        import test_api
        test_api.main()
    else:
        run_command([sys.executable, "test_api.py"])


def _safe_slug(version):
    """把版本号转成安全的文件名片段（保留字母数字和 . _ -）。"""
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in str(version)) or "unknown"


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict) and "versions" in data:
                return data
        except Exception:
            pass
    return {"active": None, "versions": []}


def save_manifest(manifest):
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)


def snapshot_version():
    """把刚写好的 data/botlane_dataset.json 按版本号快照到 data/versions/ 并更新 manifest。

    这样每次更新都会保留一份带版本号的完整数据，界面就能回切到旧版本。
    """
    if not os.path.exists(DATA_PATH):
        return
    with open(DATA_PATH, "r", encoding="utf-8") as file:
        meta = json.load(file).get("meta", {})
    version = meta.get("version") or "unknown"
    update_time = meta.get("update_time") or time.strftime("%Y-%m-%d %H:%M:%S")
    source = meta.get("version_source", "")
    os.makedirs(VERSIONS_DIR, exist_ok=True)
    dest = os.path.join(VERSIONS_DIR, f"botlane_dataset_{_safe_slug(version)}.json")
    shutil.copy2(DATA_PATH, dest)

    manifest = load_manifest()
    versions = manifest.get("versions", [])
    # 同一版本号只保留最新一次（按 update_time 去重）
    versions = [entry for entry in versions if entry.get("version") != version]
    versions.append({
        "version": version,
        "update_time": update_time,
        "file": os.path.relpath(dest, BASE_DIR).replace("\\", "/"),
        "source": source,
    })
    versions.sort(key=lambda entry: entry.get("update_time", ""), reverse=True)
    manifest["versions"] = versions
    manifest["active"] = version
    save_manifest(manifest)
    print(f"已保存版本快照: {version} -> {dest}")


def update_data(with_timeline=False, timeline_limit=None, timeline_headed=False):
    backup_path = backup_dataset()
    try:
        if FROZEN:
            # 冻结态没有独立的 pre_fetch.py 可跑，直接在本进程内执行抓取流程
            import pre_fetch
            argv = []
            if with_timeline:
                argv.append("--with-timeline")
            if timeline_limit is not None:
                argv.extend(["--timeline-limit", str(timeline_limit)])
            if timeline_headed:
                argv.append("--timeline-headed")
            pre_fetch.main(argv)
        else:
            args = [sys.executable, "pre_fetch.py"]
            if with_timeline:
                args.append("--with-timeline")
            if timeline_limit is not None:
                args.extend(["--timeline-limit", str(timeline_limit)])
            if timeline_headed:
                args.append("--timeline-headed")
            run_command(args)
        validate_dataset()
        run_api_tests()
        snapshot_version()
    except Exception:
        print("\n更新失败，准备恢复旧数据。")
        restore_backup(backup_path)
        raise

    print("\n数据更新完成。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只校验当前数据和 API，不运行 pre_fetch.py",
    )
    parser.add_argument(
        "--with-timeline",
        action="store_true",
        help="额外用 Scrapling 抓取 Lolalytics build 页时间趋势。",
    )
    parser.add_argument(
        "--timeline-limit",
        type=int,
        default=None,
        help="只抓取前 N 个时间趋势样本，便于本地测试。",
    )
    parser.add_argument(
        "--timeline-headed",
        action="store_true",
        help="使用有界面浏览器抓取时间趋势，便于手动通过 Cloudflare。",
    )
    args = parser.parse_args()

    if args.check_only:
        validate_dataset()
        run_api_tests()
        print("\n当前数据可用。")
        return

    update_data(
        with_timeline=args.with_timeline,
        timeline_limit=args.timeline_limit,
        timeline_headed=args.timeline_headed,
    )


if __name__ == "__main__":
    main()
