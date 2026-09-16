# -*- coding: utf-8 -*-
"""检查结果表格里配合/对位两列的三档着色与"-"处理。"""
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:/Users/Administrator/AppData/Local/Temp/dom_ui.html"
h = open(path, encoding="utf-8", errors="ignore").read()

# 只看 <tbody> 里的行，避免抓到 CSS 文本
rows = re.findall(r"<tr[^>]*data-champion=\"([^\"]+)\"(.*?)</tr>", h, re.S)
print("数据行数:", len(rows))
print()
print(f"{'英雄':<12}{'配合':<26}{'对位':<26}")
print("-" * 64)

stat = {"score-high": 0, "score-low": 0, "score-mid": 0, "score-none": 0}

for name, body in rows[:14]:
    cells = re.findall(r'<td class="(score-[a-z]+)"[^>]*>([^<]*)</td>', body)
    out = []
    for cls, txt in cells[:2]:
        stat[cls] = stat.get(cls, 0) + 1
        out.append(f"{txt:<10}({cls.replace('score-', '')})")
    while len(out) < 2:
        out.append("-")
    print(f"{name:<12}{out[0]:<26}{out[1]:<26}")

print()
print("全部行的档位统计:", stat)

# 确认没有把哨兵值 -17.5 露出来
sentinel = re.findall(r">(-17\.5)<", h)
print("页面上残留的哨兵值 -17.5 个数:", len(sentinel))
