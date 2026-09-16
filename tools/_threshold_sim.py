# -*- coding: utf-8 -*-
"""对比三种"是不是这条路主力"的判据，看谁扛得住版本数据量变化。

模拟：把场次整体乘以一个系数（模拟版本初期数据少 / 末期数据多），
看每个英雄的分级会不会漂移。
"""
import json
import statistics

db = json.load(open("data/botlane_dataset.json", encoding="utf-8"))
hs = db.get("hero_stats", {})

LANES = {}
for lane in ("bottom", "support"):
    rows = sorted(
        [(k, int(v.get("games", 0))) for k, v in (hs.get(lane) or {}).items()],
        key=lambda x: -x[1],
    )
    LANES[lane] = rows


def tier_abs(games, rows):
    """方案A：绝对场次（当前实现）"""
    if games >= 10000:
        return 3
    if games >= 3000:
        return 2
    if games >= 1000:
        return 1
    return 0


def tier_share(games, rows):
    """方案B：占该位置总场次的比例"""
    total = sum(g for _, g in rows) or 1
    share = games / total * 100
    if share >= 3.0:
        return 3
    if share >= 1.0:
        return 2
    if share >= 0.3:
        return 1
    return 0


def tier_pct(games, rows):
    """方案C：位置内百分位排名（不受数据量 / 榜单长度影响）"""
    n = len(rows)
    le = sum(1 for _, g in rows if g <= games)
    pct = le / n * 100
    if pct >= 85:
        return 3
    if pct >= 65:
        return 2
    if pct >= 35:
        return 1
    return 0


SCHEMES = [("A 绝对场次", tier_abs), ("B 占比%", tier_share), ("C 百分位", tier_pct)]

WATCH = {
    "bottom": ["kaisa", "jhin", "jinx", "draven", "vayne", "varus", "yasuo", "viktor", "zyra"],
    "support": ["lulu", "thresh", "nami", "soraka", "janna", "nidalee", "ziggs"],
}

for lane, rows in LANES.items():
    print("=" * 74)
    print(f"{lane}  ({len(rows)} 个英雄, 总场次 {sum(g for _, g in rows)})")
    print("=" * 74)
    header = f"{'英雄':<13}" + "".join(f"{name:>14}" for name, _ in SCHEMES)
    print(header)

    for key in WATCH[lane]:
        games = next((g for k, g in rows if k == key), 0)
        if not games:
            print(f"{key:<13}(不在榜)")
            continue
        line = f"{key:<13}{games:>8}场  "
        for _, fn in SCHEMES:
            line += f"{fn(games, rows):>12}  "
        print(line)

print()
print("=" * 74)
print("【版本进度模拟】把全部场次整体缩放，看分级会不会漂移")
print("=" * 74)

for scale, label in [(1.0, "当前(100%)"), (0.15, "版本初期(15%)"), (8.0, "版本末期(800%)")]:
    print(f"\n--- 数据量 {label} ---")
    for lane, rows in LANES.items():
        scaled = [(k, max(1, int(g * scale))) for k, g in rows]
        drift = {name: [] for name, _ in SCHEMES}
        for key in WATCH[lane]:
            g0 = next((g for k, g in rows if k == key), 0)
            g1 = next((g for k, g in scaled if k == key), 0)
            for name, fn in SCHEMES:
                if fn(g0, rows) != fn(g1, scaled):
                    drift[name].append(f"{key}:{fn(g0, rows)}→{fn(g1, scaled)}")
        out = []
        for name, _ in SCHEMES:
            d = drift[name]
            out.append(f"{name}={'稳定' if not d else '漂移 ' + ','.join(d)}")
        print(f"  {lane:8s} " + " | ".join(out))
