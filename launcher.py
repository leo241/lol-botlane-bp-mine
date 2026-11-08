#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py - 打包成 exe 后的入口

双击 exe 时会：
  1. 若是 PyInstaller 冻结环境，首次运行把全部资源（数据集/模板/头像/抓取脚本/名单）
     复制到 exe 旁的 lolbp_utils/ 下，用户可直接查看与编辑（不再散落多个顶层文件夹）。
  2. 选一个空闲端口，后台启动 Flask 服务。
  3. 自动打开默认浏览器到网页。
  4. 在系统托盘显示一个小图标：双击/菜单「打开页面」，右键菜单「退出」。
     托盘不可用（无图形界面等）时自动退化为纯服务模式，仅打印地址。

开发模式直接 `python app.py` 不受本文件影响。
"""

import os
import sys
import socket
import shutil
import threading
import time
import webbrowser

FROZEN = getattr(sys, "frozen", False)


def _copy_tree(src, dst):
    """只在目标不存在时复制，保留用户已修改的名单。"""
    if not os.path.exists(src) or os.path.exists(dst):
        return
    try:
        shutil.copytree(src, dst)
    except Exception as exc:  # 复制失败不应阻断启动
        sys.stderr.write(f"[warn] 复制 {src} 失败: {exc}\n")

def prepare_runtime():
    """冻结环境下，首次运行把全部资源（数据集/模板/头像/抓取脚本/名单）复制到 exe 旁的
    lolbp_utils/ 下，用户可直接查看与编辑；不再在 exe 旁散落多个顶层文件夹。"""
    if not FROZEN:
        return
    base = os.path.dirname(os.path.abspath(sys.executable))
    meipass = getattr(sys, "_MEIPASS", base)
    utils = os.path.join(base, "lolbp_utils")

    # 1) 首次运行：把打包进 exe 的资源复制到 lolbp_utils/（目标已存在则跳过，保留用户修改）
    for sub in ("data", "templates", "scraper", "static"):
        _copy_tree(os.path.join(meipass, sub), os.path.join(utils, sub))

    # 2) 兼容旧版：若 exe 旁已存在上一代布局（data/ templates/ scraper/ 在根目录），
    #    把其中缺失的文件并入 lolbp_utils/，避免用户改过的名单或模板丢失。
    for sub in ("data", "templates", "scraper", "static"):
        old = os.path.join(base, sub)
        if not os.path.isdir(old):
            continue
        dst_dir = os.path.join(utils, sub)
        os.makedirs(dst_dir, exist_ok=True)
        for name in os.listdir(old):
            src = os.path.join(old, name)
            dst = os.path.join(dst_dir, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass


def _find_resource(name):
    """在 PyInstaller 临时目录和 exe 目录里找打包资源。"""
    base = os.path.dirname(os.path.abspath(sys.executable))
    meipass = getattr(sys, "_MEIPASS", None)
    for d in (meipass, base):
        if d:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


def find_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def start_tray(url):
    """系统托盘图标（替代原来的弹窗窗口）。成功进入托盘消息循环后不返回。"""
    import pystray
    from PIL import Image

    icon_path = _find_resource("icon.png")
    if icon_path:
        image = Image.open(icon_path)
    else:  # 兜底：纯色占位图标
        image = Image.new("RGB", (64, 64), (37, 99, 235))

    menu = pystray.Menu(
        pystray.MenuItem("打开页面", lambda: webbrowser.open(url), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda: os._exit(0)),
    )
    icon = pystray.Icon("LolBp", image, "下路 BP 助手", menu)
    icon.run()


def main():
    prepare_runtime()
    # 延迟导入，确保 prepare_runtime 已把数据放到正确位置
    from app import app, get_db, ensure_lcu_started

    port = find_free_port()
    url = f"http://127.0.0.1:{port}/"

    get_db()
    try:
        ensure_lcu_started()
    except Exception:
        pass

    srv = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=port, debug=False, use_reloader=False
        ),
        daemon=True,
    )
    srv.start()

    # 等服务起来再开浏览器
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        start_tray(url)
    except Exception as exc:
        # 无显示器 / 托盘不可用时退化为纯服务模式
        sys.stdout.write(f"服务已启动: {url}\n(托盘不可用，纯服务模式: {exc})\n按 Ctrl+C 退出。\n")
        sys.stdout.flush()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


def _run_internal_update():
    """冻结态下由主进程 spawn 本 exe（带 --_internal_update）在子进程里跑更新流水线。

    设计要点：
      - 主进程是窗口版 exe（无控制台），它把更新子进程的标准输出接到管道，
        实时解析进度（见 app._run_update）。所以这里必须把 print 重定向回 fd 1/2 的管道，
        否则 PyInstaller 窗口版会把 stdout 接到黑洞，父进程收不到任何进度。
      - 资源在 exe 旁的 lolbp_utils/ 下，切换工作目录过去再跑，保证读写的是用户那份数据。
      - pre_fetch / test_api 在冻结态无法作为独立脚本启动（旁边没有 .py 文件），
        故由 update_data 在本进程内直接 import 调用（见 update_data.update_data 的 FROZEN 分支）。
    """
    # 把 stdout/stderr 重新指向继承来的管道（窗口版默认会被 PyInstaller 重定向到黑洞）
    try:
        sys.stdout = open(1, "w", buffering=1, closefd=False, encoding="utf-8", errors="replace")
        sys.stderr = open(2, "w", buffering=1, closefd=False, encoding="utf-8", errors="replace")
    except Exception:
        pass

    prepare_runtime()
    base = os.path.dirname(os.path.abspath(sys.executable))
    utils = os.path.join(base, "lolbp_utils")
    os.makedirs(utils, exist_ok=True)
    os.chdir(utils)

    with_timeline = "--with-timeline" in sys.argv
    try:
        import update_data
        update_data.update_data(with_timeline=with_timeline)
    except SystemExit:
        raise
    except Exception as exc:  # 让父进程能抓到真正的异常信息
        sys.stderr.write(f"UPDATE_FAILED: {exc}\n")
        raise


if __name__ == "__main__":
    if "--_internal_update" in sys.argv:
        _run_internal_update()
    else:
        main()
