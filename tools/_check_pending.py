# -*- coding: utf-8 -*-
"""检查无头渲染出的 DOM：4 个自动标签和敌方输入框的值。"""
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:/Users/Administrator/AppData/Local/Temp/dom_pending.html"
h = open(path, encoding="utf-8", errors="ignore").read()

print("=== 4 个自动标签 ===")
for tid in ["tag_ally_ad", "tag_ally_sup", "tag_enemy_ad", "tag_enemy_sup"]:
    tag_m = re.search(r'id="%s"[^>]*>([^<]*)<' % tid, h)
    cls_m = re.search(r'id="%s"[^>]*class="([^"]*)"' % tid, h)
    full_m = re.search(r'id="%s"[^>]*' % tid, h)
    text = tag_m.group(1) if tag_m else ""
    cls = cls_m.group(1) if cls_m else ""
    hidden = "hidden" in (full_m.group(0) if full_m else "")
    print("  %-15s text=%-10s class=%-32s hidden=%s" % (tid, repr(text), cls, hidden))

print("\n=== 敌方输入框 ===")
for iid in ["enemy_ad", "enemy_sup"]:
    m = re.search(r'id="%s"[^>]*value="([^"]*)"' % iid, h)
    val = m.group(1) if m else "(无 value 属性)"
    print("  input %-11s value=%s" % (iid, repr(val)))

print("\n「待定」出现次数:", h.count("待定"))
