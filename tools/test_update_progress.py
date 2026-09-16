#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据更新进度解析的测试。

不真跑 pre_fetch.py（那要 2~4 分钟还要联网），
而是把它的典型输出喂给 _handle_output，验证阶段和百分比算得对。
另外验证 Popen 能实时读到用 \\r 刷新的进度条（这是能显示进度的前提）。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LCU_DISABLED", "1")

from app import _handle_output, _extract_error, UPDATE_STATE  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = (PASS + 1, FAIL) if ok else (PASS, FAIL + 1)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: 得到 {got}，期望 {want}")


def pct_after(line):
    _handle_output(line)
    return round(UPDATE_STATE["percent"])


print("== 1) 三个大阶段要能识别 ==")
check("[1/3] 梯队阶段起点", pct_after("\n[1/3] 正在获取梯队数据..."), 5)
check("[2/3] 矩阵阶段起点", pct_after("\n[2/3] 正在获取协同与克制矩阵 (预计2-4分钟)..."), 40)
check("[3/3] 保存阶段起点", pct_after("\n[3/3] 正在保存到 data/botlane_dataset.json ..."), 85)

print("\n== 2) 进度条百分比要映射进当前阶段 ==")
# 先锁定在 [2/3] 矩阵阶段（40~85），再喂进度条
_handle_output("[2/3] 正在获取协同与克制矩阵...")
check("矩阵阶段 0%", pct_after("  [░░░░░░░░░░░░░░░░] 0% (0/50) jinx/bottom"), 40)
mid = pct_after("  [█████████░░░░░░░░░] 50% (25/50) jinx/bottom")
check("矩阵阶段 50%（应落在 40~85 之间）", 40 < mid < 85, True)
print(f"        实际 = {mid}%")
full = pct_after("  [██████████████████] 100% (50/50) jinx/bottom")
check("矩阵阶段 100%（应接近 85）", abs(full - 85) <= 1, True)
print(f"        实际 = {full}%")

print("\n== 3) update_data.py 自己的里程碑 ==")
check("已备份 → 4%", pct_after("已备份旧数据: data/backups/xxx.json"), 4)
check("校验通过 → 95%", pct_after("数据校验通过: bottom=50, support=85"), 95)
check("测试 → 97%", pct_after("$ D:\\python311\\python.exe test_api.py"), 97)
check("完成 → 100%", pct_after("\n数据更新完成。"), 100)

print("\n== 4) Popen 能实时读到 \\r 刷新的进度条 ==")
# 这是"实时显示进度"的前提：如果只能等进程结束才拿到输出，就没法做进度条
code = (
    "import sys,time\n"
    "for i in range(1,4):\n"
    "    sys.stdout.write('\\r  [%s] %d%% (%d/3) x' % ('#'*i, i*33, i))\n"
    "    sys.stdout.flush()\n"
    "    time.sleep(0.15)\n"
)
proc = subprocess.Popen(
    [sys.executable, "-u", "-c", code],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    env=dict(os.environ, PYTHONUNBUFFERED="1"),
)
seen = []
buf = ""
while True:
    chunk = proc.stdout.read(256)
    if not chunk:
        break
    for ch in chunk.decode("utf-8", errors="replace"):
        if ch in ("\r", "\n"):
            if buf.strip():
                seen.append(buf.strip())
            buf = ""
        else:
            buf += ch
if buf.strip():
    seen.append(buf.strip())
proc.wait()
check("收到 3 次进度刷新（而不是挤成一坨）", len(seen), 3)
if seen:
    print(f"        最后一次: {seen[-1]}")

print("\n== 5) 失败时要把真正原因挖出来，不能只给退出码 ==")
# update_data.py 崩溃时 traceback 会打进日志，这里要能从里面挑出关键行
traceback_logs = [
    "已备份旧数据: data/backups/x.json",
    "$ D:\\python311\\python.exe pre_fetch.py",
    "Traceback (most recent call last):",
    '  File "update_data.py", line 169, in update_data',
    "    run_command(args)",
    "CalledProcessError: Command '['D:\\python311\\python.exe', 'pre_fetch.py']' returned non-zero exit status 1.",
]
err = _extract_error(traceback_logs, 1)
ok = "pre_fetch.py" in err and "CalledProcessError" in err
PASS, FAIL = (PASS + 1, FAIL) if ok else (PASS, FAIL + 1)
print(f"  [{'PASS' if ok else 'FAIL'}] 从 traceback 提取出失败命令")
print(f"        {err[:120]}")

fallback = _extract_error(["已备份旧数据", "$ python pre_fetch.py"], 3)
ok2 = "退出码 3" in fallback
PASS, FAIL = (PASS + 1, FAIL) if ok2 else (PASS, FAIL + 1)
print(f"  [{'PASS' if ok2 else 'FAIL'}] 没有异常痕迹时退回退出码提示: {fallback}")

print(f"\n通过 {PASS} / {PASS + FAIL}")
sys.exit(1 if FAIL else 0)
