"""纯 TCP 扫描 + 只对开放端口测 LCU 接口。"""
import base64
import os
import socket
import sys
import time
import requests
import urllib3

urllib3.disable_warnings()

t0 = time.time()
print("Step 1: 纯 TCP 扫描 1-65535...", flush=True)

open_ports = []
for port in range(1, 65536):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.02)
        s.close()
        open_ports.append(port)
    except Exception:
        pass

print(f"  TCP 扫描用时 {time.time()-t0:.1f}s, 开放端口数 {len(open_ports)}", flush=True)
print(f"  开放端口: {open_ports}", flush=True)

# 注意：不要在这里写死真实 token —— 这脚本是要进 Git 的。
# 从命令行传，或者拿 lcu.py 自动探测到的（见 tools/lcu_doctor.py）。
token = os.environ.get("LCU_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not token:
    print("用法: python tools/_scan_lcu_port.py <LCU_TOKEN>")
    print("或先 export LCU_TOKEN=... 再运行。token 可从 tools/lcu_doctor.py 获取。")
    sys.exit(1)
auth = base64.b64encode(f"riot:{token}".encode()).decode()
hdr = {"Authorization": "Basic " + auth, "Accept": "application/json"}

print("\nStep 2: 对每个开放端口测 LCU 接口...", flush=True)
for port in open_ports:
    try:
        t = time.time()
        r = requests.get(
            f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
            headers=hdr, verify=False, timeout=2,
        )
        ms = (time.time() - t) * 1000
        print(f"  {port}: status={r.status_code} ({ms:.0f}ms) body={r.text[:100]!r}", flush=True)
    except requests.exceptions.SSLError as e:
        msg = str(e)[:50]
        print(f"  {port}: SSL {msg!r}", flush=True)
    except Exception as e:
        print(f"  {port}: {type(e).__name__}: {str(e)[:50]}", flush=True)
