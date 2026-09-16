#!/usr/bin/env bash
# 用法: bash tools/e2e_check.sh <scenario> [my_position]
# 重启模拟器 -> 等监听轮询 -> 无头 Edge 渲染 -> 解析 DOM
set -u
SCEN="${1:-full}"
POS="${2:-utility}"
ROOT="E:/lol bp/lol-botlane-bp-mine-v2"
TMP="C:/Users/Administrator/AppData/Local/Temp"
PY="D:/python311/python.exe"
EDGE="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

# 1) 杀掉旧的模拟器
"$PY" "$ROOT/tools/_kill_port.py" 54321
sleep 1

# 2) 启动新模拟器（独立端口，避免和残留进程撞车）
cd "$ROOT" || exit 1
"$PY" tools/mock_lcu.py --port 54321 --token mock-token --scenario "$SCEN" --my-position "$POS" --seconds 180 \
  >"$TMP/mock_$SCEN.log" 2>&1 &
sleep 3

# 3) 等 app 轮询到新状态
sleep 5

# 4) 渲染
rm -rf "$TMP/edge-$SCEN"
"$EDGE" --headless=new --disable-gpu --no-sandbox --dump-dom --virtual-time-budget=10000 \
  --user-data-dir="$TMP/edge-$SCEN" "http://127.0.0.1:8000/" >"$TMP/dom_$SCEN.html" 2>/dev/null

echo "=========== scenario=$SCEN  my_position=$POS ==========="
"$PY" tools/_dom_check.py "$TMP/dom_$SCEN.html"
