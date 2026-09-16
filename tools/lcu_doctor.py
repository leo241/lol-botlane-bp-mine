#!/usr/bin/env python3
"""LCU 探测诊断：把每一步的中间结果都打出来，方便排查"识别不到客户端"的问题。"""
import base64
import os
import sys
import time

# 让脚本能 import 到 v2 项目里的 lcu.py
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import lcu  # noqa: E402

import requests  # noqa: E402
import urllib3  # noqa: E402
urllib3.disable_warnings()


def line(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def ok(msg):
    print(f"  [OK]   {msg}")


def miss(msg):
    print(f"  [no]   {msg}")


def main():
    line("1) 环境变量")
    for k in ("LCU_LOCKFILE", "LCU_PORT", "LCU_TOKEN", "LCU_DISABLED", "LCU_INTERVAL"):
        v = os.environ.get(k)
        if v:
            ok(f"{k} = {v}")
        else:
            miss(f"{k} 未设置")

    line("2) lockfile 扫描")
    found_lockfile = False
    for path in lcu._iter_lockfiles():
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                ok(f"{path}")
                ok(f"   内容: {content[:80]}")
                port, token = lcu._parse_lockfile_content(content)
                if port:
                    ok(f"   解析端口={port} token={token[:8]}...")
                found_lockfile = True
            except Exception as e:
                miss(f"{path} (读失败: {e})")
    if not found_lockfile:
        miss("所有候选路径都没有 lockfile")
        miss("提示：LOL 必须完全进入客户端（不是登录页）才会写 lockfile")
        miss("     而且只在 LOL 主程序启动时写一次，关闭客户端会消失")

    line("3) 进程命令行扫描")
    cmds = lcu._scan_processes_commandline()
    if cmds:
        for port, token, src in cmds:
            ok(f"端口={port} token={token[:8]}... 来源={src}")
    else:
        miss("没在 LeagueClientUx / LeagueClient / RiotClientServices 的命令行里找到 --app-port / --remoting-auth-token")
        miss("可能原因：")
        miss("  - LOL 客户端还没启动（只打开了 Riot 启动器不算）")
        miss("  - LOL 用了非标准启动方式（WeGame、腾讯 LOL 助手等代理启动）")
        miss("  - 当前进程权限不足，看不到 LOL 进程的命令行（见下文说明）")

    line("4) 接口探测（拿端口试着请求 /lol-summoner/v1/current-summoner）")
    if not cmds and not found_lockfile:
        miss("没有可用的端口，跳过接口测试")
    else:
        seen = set()
        for port, token, src in (cmds or []):
            if (port, token) in seen:
                continue
            seen.add((port, token))
            try:
                auth = base64.b64encode(f"riot:{token}".encode()).decode()
                t0 = time.time()
                r = requests.get(
                    f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
                    headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
                    verify=False, timeout=3,
                )
                dt = (time.time() - t0) * 1000
                if r.status_code == 200:
                    ok(f"{src}: 状态 {r.status_code} ({dt:.0f}ms) → 是真的游戏客户端")
                else:
                    miss(f"{src}: 状态 {r.status_code} ({dt:.0f}ms) → 是启动器，不是游戏客户端")
            except Exception as e:
                miss(f"{src}: 请求失败 {type(e).__name__}: {e}")

    line("5) 最终：find_lcu_process()")
    port, token, src = lcu.find_lcu_process()
    if port:
        ok(f"识别成功 → 端口={port} 来源={src}")
        ok("接下来 app.py 会自动开始监听选人阶段")
    else:
        miss("依然没识别到（上面 1~4 步是详细原因）")

    line("6) 关于管理员权限")
    print("  LCU 监听的是 127.0.0.1 的本地回环地址，不需要管理员权限。")
    print("  真正需要管理员权限的情况只有：")
    print("    - LOL 客户端本身用了管理员启动（很少见，但你会发现任务管理器里")
    print("      LeagueClientUx.exe 后面带了一个盾牌图标）")
    print("    - 你的本机开了第三方安全软件（360、电脑管家、火绒等）拦截 Python 进程")
    print("  大多数情况都不需要管理员。先看上面 1~4 步的输出再下结论。")


if __name__ == "__main__":
    main()
    print()
    input("按回车退出…")
