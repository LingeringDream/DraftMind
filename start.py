#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DraftMind 跨平台统一启动脚本 (Win / Mac / Linux)
"""
import os
import sys
import platform
import subprocess
import time
import urllib.request

def resolve_python():
    """自动探测虚拟环境或系统 Python，兼容 Windows 与 Unix 路径差异"""
    if platform.system() == "Windows":
        venv_paths = [os.path.join(".venv", "Scripts", "python.exe"),
                      os.path.join("venv", "Scripts", "python.exe")]
    else:
        venv_paths = [os.path.join(".venv", "bin", "python"),
                      os.path.join("venv", "bin", "python")]

    for path in venv_paths:
        if os.path.isfile(path):
            return path
    return sys.executable

def wait_for_backend(url="http://127.0.0.1:5000", timeout=30):
    """轮询检测 Flask """
    print("Waiting for backend readiness...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    python_exe = resolve_python()

    backend_file = os.path.join(os.getcwd(), "backend.py")
    frontend_file = os.path.join(os.getcwd(), "frontend.py")

    # 严格校验核心文件是否存在，缺失则阻断流程
    if not os.path.exists(backend_file):
        raise FileNotFoundError("backend.py was not found.")
    if not os.path.exists(frontend_file):
        raise FileNotFoundError("frontend.py was not found.")

    print("Starting DraftMind backend...")
    # 独立子进程启动后端服务，确保主进程可以继续执行后续逻辑
    backend_proc = subprocess.Popen([python_exe, backend_file])

    if wait_for_backend():
        print("Backend is ready. Starting frontend...")
        # 启动 Streamlit 前端
        subprocess.Popen([python_exe, "-m", "streamlit", "run", frontend_file])
        print("DraftMind processes have been started.")
    else:
        print("[ERROR] Backend failed to start within timeout.")
        backend_proc.kill()
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}")

