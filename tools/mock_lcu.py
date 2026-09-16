#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地模拟 LCU 客户端，用于在没有英雄联盟客户端的情况下测试自动填充功能。

用法：
    python tools/mock_lcu.py --port 54321 --token mock-token
    python tools/mock_lcu.py --scenario empty      # 模拟"不在英雄选择"
    python tools/mock_lcu.py --scenario full       # 双方满编
    python tools/mock_lcu.py --scenario partial    # 敌方只锁了 2 个

它会写一个 lockfile 到 tools/.mock_lockfile，测试时设置环境变量：
    LCU_LOCKFILE=<项目>/tools/.mock_lockfile
"""

import argparse
import json
import os
import ssl
import sys
import threading
import time

from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCKFILE = os.path.join(BASE_DIR, ".mock_lockfile")

# 英雄 ID 简表（取自项目映射，够测试用）
ID = {
    "caitlyn": 51, "jinx": 222, "thresh": 412, "lulu": 117, "morgana": 25,
    "ahri": 103, "garen": 86, "leesin": 64, "yasuo": 157, "zed": 238,
    "kaisa": 145, "nautilus": 111, "ashe": 22, "senna": 235, "swain": 50,
    "xerath": 101, "masteryi": 11, "janna": 40, "ezreal": 81, "brand": 63,
}


def build_session(scenario, my_position="utility"):
    if scenario == "empty":
        return None

    my_team = [
        {"cellId": 0, "assignedPosition": "top", "championId": ID["garen"], "championPickIntent": 0},
        {"cellId": 1, "assignedPosition": "jungle", "championId": ID["leesin"], "championPickIntent": 0},
        {"cellId": 2, "assignedPosition": my_position, "championId": ID["lulu"] if my_position == "utility" else ID["jinx"],
         "championPickIntent": 0},
        {"cellId": 3, "assignedPosition": "middle", "championId": ID["ahri"], "championPickIntent": 0},
        {"cellId": 4, "assignedPosition": "bottom" if my_position == "utility" else "utility",
         "championId": ID["jinx"] if my_position == "utility" else ID["lulu"], "championPickIntent": 0},
    ]
    their_team = [
        {"cellId": 5, "assignedPosition": "", "championId": ID["caitlyn"], "championPickIntent": 0},
        {"cellId": 6, "assignedPosition": "", "championId": ID["morgana"], "championPickIntent": 0},
        {"cellId": 7, "assignedPosition": "", "championId": ID["yasuo"], "championPickIntent": 0},
        {"cellId": 8, "assignedPosition": "", "championId": ID["zed"], "championPickIntent": 0},
        {"cellId": 9, "assignedPosition": "", "championId": ID["janna"], "championPickIntent": 0},
    ]

    if scenario == "partial":
        their_team = [
            {"cellId": 5, "assignedPosition": "", "championId": ID["caitlyn"], "championPickIntent": 0},
            {"cellId": 6, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
            {"cellId": 7, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
            {"cellId": 8, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
            {"cellId": 9, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
        ]

    if scenario == "ambig":
        # 敌方两个摇摆英雄，考验推断
        their_team = [
            {"cellId": 5, "assignedPosition": "", "championId": ID["ashe"], "championPickIntent": 0},
            {"cellId": 6, "assignedPosition": "", "championId": ID["senna"], "championPickIntent": 0},
            {"cellId": 7, "assignedPosition": "", "championId": ID["swain"], "championPickIntent": 0},
            {"cellId": 8, "assignedPosition": "", "championId": ID["xerath"], "championPickIntent": 0},
            {"cellId": 9, "assignedPosition": "", "championId": ID["brand"], "championPickIntent": 0},
        ]

    if scenario == "hard":
        # 下路两个都是"两边都能打"的类型，推断可信度会降级
        their_team = [
            {"cellId": 5, "assignedPosition": "", "championId": ID["swain"], "championPickIntent": 0},
            {"cellId": 6, "assignedPosition": "", "championId": ID["xerath"], "championPickIntent": 0},
            {"cellId": 7, "assignedPosition": "", "championId": ID["garen"], "championPickIntent": 0},
            {"cellId": 8, "assignedPosition": "", "championId": ID["leesin"], "championPickIntent": 0},
            {"cellId": 9, "assignedPosition": "", "championId": ID["ahri"], "championPickIntent": 0},
        ]

    if scenario == "one":
        # 敌方只锁了 1 个人
        their_team = [
            {"cellId": 5, "assignedPosition": "", "championId": ID["caitlyn"], "championPickIntent": 0},
            {"cellId": 6, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
            {"cellId": 7, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
            {"cellId": 8, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
            {"cellId": 9, "assignedPosition": "", "championId": 0, "championPickIntent": 0},
        ]

    return {
        "localPlayerCellId": 2,
        "queueId": 420,
        "myTeam": my_team,
        "theirTeam": their_team,
        "actions": [[
            {"type": "ban", "completed": True, "championId": ID["yasuo"], "actorCellId": 0},
            {"type": "ban", "completed": True, "championId": ID["zed"], "actorCellId": 5},
            {"type": "ban", "completed": True, "championId": ID["ezreal"], "actorCellId": 1},
            {"type": "ban", "completed": True, "championId": ID["brand"], "actorCellId": 6},
        ]],
        "timer": {
            "phase": "BAN_PICK",
            "totalTime": 30000,
            "adjustedTimeLeftInPhase": 21000,
        },
    }


class Handler(BaseHTTPRequestHandler):
    scenario = "full"
    my_position = "utility"

    def log_message(self, *args):
        pass  # 静音访问日志

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/lol-summoner/v1/current-summoner"):
            return self._send(200, {"displayName": "MockPlayer", "summonerId": 1})
        if self.path.startswith("/lol-champ-select/v1/session"):
            session = build_session(self.scenario, self.my_position)
            if session is None:
                return self._send(404, {"message": "No active session"})
            return self._send(200, session)
        if self.path.startswith("/lol-gameflow/v1/gameflow-phase"):
            phase = "ChampSelect" if self.scenario != "empty" else "None"
            body = json.dumps(phase).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self._send(404, {"message": "not found"})


def make_cert():
    """复用 tools/ 下已有的自签名证书（用 openssl 生成，见文件头注释）。"""
    cert = os.path.join(BASE_DIR, ".mock_cert.pem")
    key = os.path.join(BASE_DIR, ".mock_key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=54321)
    parser.add_argument("--token", default="mock-token")
    parser.add_argument("--scenario", default="full",
                        choices=["full", "partial", "ambig", "hard", "one", "empty"])
    parser.add_argument("--my-position", default="utility",
                        choices=["top", "jungle", "middle", "bottom", "utility"],
                        help="模拟'我'被分到的位置（bottom=ADC，utility=辅助）")
    parser.add_argument("--seconds", type=float, default=0, help="运行多少秒后自动退出（0=一直运行）")
    args = parser.parse_args()

    Handler.scenario = args.scenario
    Handler.my_position = args.my_position
    server = HTTPServer(("127.0.0.1", args.port), Handler)

    cert, key = make_cert()
    if cert and key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        print(f"[mock-lcu] HTTPS 模式，场景={args.scenario}，端口={args.port}")
    else:
        print("[mock-lcu] 警告：没有 cryptography 库，退化为 HTTP（lcu.py 走 HTTPS 会失败）",
              file=sys.stderr)

    with open(LOCKFILE, "w", encoding="utf-8") as f:
        f.write(f"LeagueClient:1234:{args.port}:{args.token}:https")

    print(f"[mock-lcu] lockfile -> {LOCKFILE}")
    print(f"[mock-lcu] 测试时设置环境变量 LCU_LOCKFILE={LOCKFILE}")

    if args.seconds:
        timer = threading.Timer(args.seconds, server.shutdown)
        timer.daemon = True
        timer.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(LOCKFILE):
            os.remove(LOCKFILE)
        print("[mock-lcu] 已退出")


if __name__ == "__main__":
    main()
