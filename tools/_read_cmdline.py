"""用 win32 API 读指定 PID 进程的完整命令行（不依赖 WMI/wmic）。"""
import ctypes
from ctypes import wintypes
import sys

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010

OpenProcess = ctypes.windll.kernel32.OpenProcess
OpenProcess.restype = wintypes.HANDLE
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

CloseHandle = ctypes.windll.kernel32.CloseHandle

ntdll = ctypes.windll.ntdll

# 0x10E = ProcessCommandLineInformation (Win 10 1607+)
PROCESS_BASIC_INFORMATION = 0


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p * 2),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 4),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_wchar_p),
    ]


def get_cmdline(pid):
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        return None
    try:
        pbi = PROCESS_BASIC_INFORMATION()
        ret = ntdll.NtQueryInformationProcess(
            h, PROCESS_BASIC_INFORMATION, ctypes.byref(pbi), ctypes.sizeof(pbi), None
        )
        if ret != 0:
            return None

        peb = pbi.PebBaseAddress
        if not peb:
            return None

        # PEB offset 0x20 (Win 10) = ProcessParameters (RTL_USER_PROCESS_PARAMETERS)
        process_params = ctypes.c_void_p()
        ctypes.memmove(ctypes.byref(process_params), peb + 0x20, ctypes.sizeof(process_params))

        # ProcessParameters offset 0x70 (Win 10 64-bit) = CommandLine (UNICODE_STRING)
        cmdline = UNICODE_STRING()
        ctypes.memmove(ctypes.byref(cmdline), process_params.value + 0x70, ctypes.sizeof(cmdline))

        if cmdline.Buffer:
            # Length 是字节数，要除以 2
            chars = cmdline.Length // 2
            try:
                buf = ctypes.create_unicode_buffer(cmdline.Buffer, chars + 1)
                return buf.value
            except Exception as e:
                return f"(decode err {e})"
        return ""
    finally:
        CloseHandle(h)


if __name__ == "__main__":
    target_pids = [33020, 33032, 9140]
    for pid in target_pids:
        cmd = get_cmdline(pid)
        if cmd is None:
            print(f"PID {pid}: cannot read (need admin or unsupported)", flush=True)
            continue
        if "--app-port" in cmd or "--remoting" in cmd:
            print(f"=== PID {pid} (HAS --app-port) ===", flush=True)
            # 高亮关键参数
            import re

            for m in re.finditer(
                r"--(app-port|remoting-auth-token|riotclient-app-port|riotclient-auth-token)=([^\s]+)",
                cmd,
            ):
                print(f"  >>> {m.group(0)}", flush=True)
            print(f"  full: {cmd[:600]}", flush=True)
            print("", flush=True)
        else:
            print(f"PID {pid}: no --app-port in cmdline (len={len(cmd)})", flush=True)
            print(f"  first 200 chars: {cmd[:200]}", flush=True)
            print("", flush=True)
