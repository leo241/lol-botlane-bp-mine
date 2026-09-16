#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析无头浏览器导出的 DOM，检查自动填入是否生效（测试用，可删）。"""
import io
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/Administrator/AppData/Local/Temp/bp_dom.html"
html = io.open(path, encoding="utf-8", errors="replace").read()

def grab(pat, default="<<NOT FOUND>>"):
    m = re.search(pat, html, re.S)
    return m.group(1).strip() if m else default

print("bar classes :", grab(r'<section class="(lcu-bar[^"]*)" id="lcu_bar"'))
print("bar text    :", grab(r'id="lcu_text"[^>]*>(.*?)</span>'))
print("bar sub     :", grab(r'id="lcu_sub"[^>]*>(.*?)</span>'))
m = re.search(r'<span class="lcu-timer" id="lcu_timer"([^>]*)>(.*?)</span>', html, re.S)
if m:
    print("bar timer   :", "hidden" if "hidden" in m.group(1) else repr(m.group(2)))
print()
for i in ("ally_ad", "ally_sup", "enemy_ad", "enemy_sup"):
    m = re.search(r'<input id="%s"([^>]*)>' % i, html)
    attrs = m.group(1) if m else ""
    print("%-10s filled=%-5s" % (i, "lcu-filled" in attrs))
print()
for t in ("tag_ally_ad", "tag_ally_sup", "tag_enemy_ad", "tag_enemy_sup"):
    m = re.search(r'<span class="(auto-tag[^"]*)" id="%s"([^>]*)>(.*?)</span>' % t, html, re.S)
    if m:
        print("%-14s cls=%-22s hidden=%-5s text=%r" % (t, m.group(1), "hidden" in m.group(2), m.group(3)))
    else:
        print(t, "<<NOT FOUND>>")
print()
print("status      :", grab(r'id="status"[^>]*>(.*?)</span>').split("<")[0][:120])
print("excluded    :", grab(r'已排除已选英雄：([^<]*)'))
for m in re.finditer(r'<button[^>]*data-role="(\w+)"[^>]*>', html):
    tag = m.group(0)
    print("role button :", re.search(r'data-role="(\w+)"', tag).group(1),
          "ACTIVE" if 'class="active"' in tag else "")
