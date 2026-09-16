#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敌方下路识别回归测试。

背景：LCU 不公开敌方位置，只能靠英雄本身猜谁是 ADC、谁是辅助。
早期版本用 tiers 的 S+/S 评级判断"是不是下路英雄"，结果把
nidalee(辅助 390 场但评级 S)、yasuo(下路 2497 场但主打中单)
这类客串英雄当成了主力，硬填进槽位。

现在改用工单场次分级 + "没把握就不填"，这套测试守住这个行为。

运行： python tools/test_lane_inference.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lcu import _rank_tiers, infer_botlane_roles, score_lanes  # noqa: E402

PASS = 0
FAIL = 0


def picks(*keys):
    return [{"champion_id": i, "key": k} for i, k in enumerate(keys, 1)]


def check(name, got, want_adc, want_sup):
    global PASS, FAIL
    adc, sup = got["adc"], got["support"]
    ok = adc[0] == want_adc and sup[0] == want_sup
    if ok:
        PASS += 1
    else:
        FAIL += 1

    def fmt(v):
        return f"{v[0]}({v[1]})" if v[0] else "空"

    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}")
    print(f"         ADC={fmt(adc)}  辅助={fmt(sup)}"
          f"  期望 ADC={want_adc or '空'} 辅助={want_sup or '空'}")


print("== 1) 场次分级：主力 vs 客串 ==")
# 卡莎下路 42512 场 → 3 分；亚索下路 2497 场 → 1 分；豹女辅助 390 场 → 0 分
check_score = [
    ("kaisa 是真 ADC（42512 场）", score_lanes("kaisa"), (3, 0)),
    ("thresh 是真辅助（21397 场）", score_lanes("thresh"), (0, 3)),
    ("yasuo 只是客串下路（2497 场）", score_lanes("yasuo"), (1, 0)),
    ("nidalee 辅助是黑科技（390 场）", score_lanes("nidalee"), (0, 0)),
    ("zed 跟下路没关系", score_lanes("zed"), (0, 0)),
]
for name, got, want in check_score:
    ok = got == want
    globals()["PASS" if ok else "FAIL"]  # noqa: B018
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: 得到 {got}，期望 {want}")

print("\n== 2) 敌方出的人不是下路 → 坚决不填 ==")
check("只出亚索（中单客串下路）", infer_botlane_roles(picks("yasuo")), None, None)
check("只出豹女（打野黑科技辅助）", infer_botlane_roles(picks("nidalee")), None, None)
check("亚索+劫+盲僧（上中野）", infer_botlane_roles(picks("yasuo", "zed", "monkeyking")),
      None, None)
check("盖伦+诺手+剑圣（全上野）", infer_botlane_roles(picks("garen", "darius", "masteryi")),
      None, None)

print("\n== 3) 标准下路组合 → 高置信填上 ==")
check("卡莎+锤石", infer_botlane_roles(picks("kaisa", "thresh")), "kaisa", "thresh")
check("金克丝+璐璐", infer_botlane_roles(picks("jinx", "lulu")), "jinx", "lulu")
check("艾希+婕拉", infer_botlane_roles(picks("ashe", "zyra")), "ashe", "zyra")

print("\n== 4) 场次中等的真下路 → 仍然要填（不能误伤） ==")
check("德莱文+娜美", infer_botlane_roles(picks("draven", "nami")), "draven", "nami")
check("维恩+索拉卡", infer_botlane_roles(picks("vayne", "soraka")), "vayne", "soraka")

print("\n== 5) 不硬凑：只有一边认得出来就只填一边 ==")
# 亚索(1,0) 和 卡莎(3,0) 都只像 ADC，没有像辅助的 → 辅助位必须空着
check("亚索+卡莎（俩都像 ADC）", infer_botlane_roles(picks("yasuo", "kaisa")), "kaisa", None)

print("\n== 6) 满员时能从 5 人里挑出下路两人 ==")
check("卡莎+锤石混在亚索劫盲僧里",
      infer_botlane_roles(picks("kaisa", "thresh", "yasuo", "zed", "monkeyking")),
      "kaisa", "thresh")

print("\n== 7) 边界：空输入 / 认不出的新英雄 ==")
check("没有 picks", infer_botlane_roles([]), None, None)
check("key 是 None（新英雄）", infer_botlane_roles([{"champion_id": 999, "key": None}]),
      None, None)

print("\n== 8) 判据不能随版本数据量漂移 ==")
# 这条最关键：Lolalytics 的场次会随版本进度整体放大/缩小。
# 早期用绝对场次(>=10000/3000/1000)定档，版本初期真主力全掉到 0 分、
# 版本末期连亚索下路都能混成 3 分主力。现在改用位置内百分位，缩放必须无感。
raw = {"kaisa": 42512, "jinx": 20414, "draven": 2677,
       "yasuo": 2497, "nidalee": 390, "zyra": 139}
base = _rank_tiers(raw)
print(f"  基准分级: {base}")
for scale in (0.02, 0.15, 0.5, 2, 8, 50):
    scaled = {k: max(1, int(v * scale)) for k, v in raw.items()}
    got = _rank_tiers(scaled)
    ok = got == base
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] 数据量 x{scale}: {got}")

print("\n== 9) 长度不同的榜单也能比 ==")
# 百分位按名次归一化，所以 50 人的榜和 85 人的榜可以直接比
short = _rank_tiers({f"c{i}": 10000 - i * 100 for i in range(20)})
ok = short["c0"] == 3 and short["c19"] == 0
PASS, FAIL = (PASS + 1, FAIL) if ok else (PASS, FAIL + 1)
print(f"  [{'PASS' if ok else 'FAIL'}] 20 人小榜：第 1 名={short['c0']}(应3) "
      f"第 20 名={short['c19']}(应0)")

print(f"\n通过 {PASS} / {PASS + FAIL}")
sys.exit(1 if FAIL else 0)
