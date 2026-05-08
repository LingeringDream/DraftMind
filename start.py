#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DraftMind 跨平台统一启动脚本 (Win / Mac / Linux)

一键启动 Flask 后端 + Vue.js (Vite) 前端开发服务器。
"""
import os
import sys
import platform
import subprocess
import signal
import time
import urllib.request

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 5000
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
BACKEND_TIMEOUT = 30  # 等待后端就绪的超时时间（秒）

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def resolve_python():
    """自动探测虚拟环境或系统 Python，兼容 Windows 与 Unix 路径差异"""
    if platform.system() == "Windows":
        venv_paths = [
            os.path.join(".venv", "Scripts", "python.exe"),
            os.path.join("venv", "Scripts", "python.exe"),
        ]
    else:
        venv_paths = [
            os.path.join(".venv", "bin", "python"),
            os.path.join("venv", "bin", "python"),
        ]

    for path in venv_paths:
        if os.path.isfile(path):
            return path
    return sys.executable


def resolve_npm():
    """探测 npm 命令路径"""
    if platform.system() == "Windows":
        # Windows 下 npm 通常是 npm.cmd
        for cmd in ("npm.cmd", "npm"):
            try:
                subprocess.run([cmd, "--version"], capture_output=True, check=True)
                return cmd
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    else:
        try:
            subprocess.run(["npm", "--version"], capture_output=True, check=True)
            return "npm"
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    return None


def wait_for_backend(url=BACKEND_URL, timeout=BACKEND_TIMEOUT):
    """轮询检测 Flask 后端是否就绪"""
    print(f"  Waiting for backend at {url} ...")
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


def kill_proc(proc):
    """安全终止子进程"""
    if proc is None or proc.poll() is not None:
        return
    try:
        if platform.system() == "Windows":
            proc.kill()
        else:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    python_exe = resolve_python()
    npm_exe = resolve_npm()

    backend_file = os.path.join(os.getcwd(), "backend.py")
    package_json = os.path.join(os.getcwd(), "package.json")

    # --- 校验核心文件 ---
    if not os.path.exists(backend_file):
        raise FileNotFoundError("backend.py was not found.")
    if npm_exe is None:
        raise FileNotFoundError(
            "npm was not found. Please install Node.js (>= 20.19) first.\n"
            "  Download: https://nodejs.org/"
        )
    if not os.path.exists(package_json):
        raise FileNotFoundError(
            "package.json was not found. Run 'npm install' first."
        )

    # --- 自动安装前端依赖 ---
    # 如果 node_modules 目录不存在，自动执行 npm install
    node_modules = os.path.join(os.getcwd(), "node_modules")
    if not os.path.isdir(node_modules):
        print("[0/2] Installing frontend dependencies (npm install) ...")
        install_proc = subprocess.run(
            [npm_exe, "install"],
            cwd=os.getcwd(),
            shell=(platform.system() == "Windows"),
        )
        if install_proc.returncode != 0:
            print("[ERROR] npm install failed. Please run 'npm install' manually.")
            sys.exit(1)
        print("  Frontend dependencies installed.")

    backend_proc = None
    frontend_proc = None

    try:
        # --- 启动 Flask 后端 ---
        print("[1/2] Starting Flask backend ...")
        backend_proc = subprocess.Popen(
            [python_exe, backend_file],
            cwd=os.getcwd(),
        )

        if not wait_for_backend():
            print("[ERROR] Backend failed to start within timeout.")
            kill_proc(backend_proc)
            sys.exit(1)
        print(f"  Backend ready at {BACKEND_URL}")

        # --- 启动 Vite 前端 ---
        print("[2/2] Starting Vue.js frontend (Vite) ...")
        frontend_proc = subprocess.Popen(
            [npm_exe, "run", "dev"],
            cwd=os.getcwd(),
            shell=(platform.system() == "Windows"),
        )

        print()
        print("=" * 50)
        print("  DraftMind is running!")
        print(f"  Backend : {BACKEND_URL}")
        print(f"  Frontend: http://localhost:5173")
        print("  Press Ctrl+C to stop all services.")
        print("=" * 50)
        print()

        # 等待任一子进程退出
        while True:
            if backend_proc.poll() is not None:
                print("[WARN] Backend exited unexpectedly.")
                break
            if frontend_proc.poll() is not None:
                print("[WARN] Frontend exited unexpectedly.")
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down ...")
    finally:
        kill_proc(frontend_proc)
        kill_proc(backend_proc)
        print("DraftMind stopped.")


if __name__ == "__main__":
    main()
