#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结束占用指定端口的进程（测试辅助脚本，可删）。

Git Bash 里 taskkill 的参数会被 MSYS 改写，所以在 Python 里直接调 taskkill。
"""
import re
import subprocess
import sys

port = sys.argv[1] if len(sys.argv) > 1 else "54321"
out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                     encoding="utf-8", errors="replace").stdout
pids = set()
for line in out.splitlines():
    if ":{}".format(port) in line and "LISTENING" in line.upper():
        parts = line.split()
        if parts and parts[-1].isdigit():
            pids.add(parts[-1])
for pid in pids:
    r = subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("[kill_port] {} -> {}".format(pid, (r.stdout or r.stderr).strip()[:80]))
if not pids:
    print("[kill_port] 端口 {} 没有监听进程".format(port))
