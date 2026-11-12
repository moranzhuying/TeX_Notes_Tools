#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_gui.py — 工具集图形面板（本地网页，纯标准库）

与 launcher.py 共用同一份 MENU（直接 import，只有一处定义）。区别在运行方式：

- **交互面板类**（多数工具）→ 弹出独立控制台窗口。这些工具是 input() 循环，
  必须有真终端才跑得动，行为与命令行完全一致。
- **一次性命令类**（check_sensitive / sync_paths）→ 捕获输出，结果显示在页面里，
  省得开一个跑完就消失的黑窗。

    python panel_gui.py                 # 打开面板（127.0.0.1:7658）
    python panel_gui.py --port 7660     # 换端口
    python panel_gui.py --no-browser    # 只起服务，不自动开浏览器

只绑回环地址；POST 需要页面内嵌的随机令牌，别的网页无法代你启动进程。
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TOOLS_ROOT = Path(__file__).resolve().parent
WORKSPACE = TOOLS_ROOT.parent
HTML_FILE = TOOLS_ROOT / "panel_gui.html"
DEFAULT_PORT = 7658
MAX_LINES = 4000

sys.path.insert(0, str(TOOLS_ROOT))
import launcher  # noqa: E402  —— 复用 MENU / split_args，避免两处维护

MENU = launcher.MENU
SUBMIT_NO = launcher.SUBMIT_NO

#: 每个工具的一句话说明（面板卡片上显示；标题本身偏长，需要更短的补充）
DESCRIPTIONS = {
    "1": "检测 python / git / ssh 版本，配置账户与 443 端口",
    "2": "查看各笔记仓库状态、批量提交推送、新建远程仓库",
    "3": "符号的提取 / 回填 / 删除 / 修改，并分发到各笔记",
    "4": "写作工作台服务器，默认只读，按书单独授权写入",
    "5": "从模板复制骨架建一本新笔记，可套大纲生成章节",
    "6": "从 main.tex 导出大纲、校验大纲与目录是否一致",
    "7": "单本笔记的快捷入口：提交、习题模式、补导引与小结",
    "8": "清理 aux / log / xdv / synctex 等编译产物",
    "9": "检查规范副本、误跟踪文件、未提交改动",
    "10": "扫描仓库里是否混入本机路径、密钥、用户名",
    "11": "检查配置里的路径是否有效，并按需修复",
    "12": "把本工具集仓库 add → commit → push",
    "13": "视频转文字：字幕优先，无字幕走本地 whisper",
    "14": "项目规范在多个仓库之间的副本一致性检查与同步",
    "15": "把横躺的课件 PDF 就地转正为 16:9，不重编码",
    "16": "监测笔记目录，有改动自动提交推送，并按上限裁剪历史",
}

LOCK = threading.Lock()
RUNNING = {}  # id -> {"proc", "mode", "started", "output": deque, "returncode"}


def python_exe():
    """用 python.exe 而不是 pythonw.exe：后者没有控制台，子工具会看不见输出。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        alt = exe.with_name("python.exe")
        if alt.is_file():
            return str(alt)
    return str(exe)


PYTHON = python_exe()


class InputError(ValueError):
    pass


def tool_by_id(key):
    return next((m for m in MENU if m[0] == key), None)


def pump(rec, proc):
    """把一次性命令的输出读进环形缓冲，进程结束后记下退出码。"""
    try:
        for line in proc.stdout:
            rec["output"].append(line.rstrip("\n"))
    except (OSError, ValueError):
        pass
    finally:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        rec["returncode"] = proc.poll()


def launch(key, extra=""):
    """启动一个工具。返回记录。extra 是追加参数（仅一次性命令用得上）。"""
    item = tool_by_id(key)
    if item is None:
        raise InputError("未知工具编号")
    _no, _title, rel, mode, _grp = item
    script = TOOLS_ROOT / rel
    if not script.is_file():
        raise InputError("找不到脚本：{}".format(rel))

    args = [PYTHON, str(script)]
    if mode.startswith(("参数:", "后台:")):
        args += launcher.split_args(mode.split(":", 1)[1])
    if extra and extra.strip():
        if not mode.startswith(("参数:", "后台:")):
            raise InputError("该工具是交互面板，不接受追加参数")
        args += launcher.split_args(extra)

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    oneoff = mode.startswith("参数:")
    if oneoff:
        proc = subprocess.Popen(
            args, cwd=str(script.parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True,
            encoding="utf-8", errors="replace",
            creationflags=flags)
        rec = {"proc": proc, "mode": "capture", "started": time.time(),
               "output": deque(maxlen=MAX_LINES), "returncode": None}
        threading.Thread(target=pump, args=(rec, proc), daemon=True).start()
    else:
        # 交互面板必须有真终端：python 的 input() 在无控制台时直接抛 OSError
        proc = subprocess.Popen(
            args, cwd=str(script.parent),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        rec = {"proc": proc, "mode": "console", "started": time.time(),
               "output": deque(maxlen=MAX_LINES), "returncode": None}
    return rec

def stop(key):
    """终止该工具最近一次启动的进程（含子进程）。"""
    with LOCK:
        rec = RUNNING.get(key)
    if rec is None:
        raise InputError("该工具当前没有运行")
    proc = rec["proc"]
    if proc.poll() is not None:
        return "已结束，无需停止"
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, stdin=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.terminate()
    return "已发送停止信号"


def snapshot():
    tools = []
    for no, title, rel, mode, grp in MENU:
        tools.append({
            "id": no,
            "title": title,
            "script": rel,
            "mode": mode,
            "group": grp,
            "desc": DESCRIPTIONS.get(no, ""),
            "submit": no == SUBMIT_NO,
            "oneoff": mode.startswith("参数:"),
            "defaultArgs": mode.split(":", 1)[1] if mode.startswith("参数:") else "",
            "exists": (TOOLS_ROOT / rel).is_file(),
        })

    runs = {}
    with LOCK:
        items = list(RUNNING.items())
    for key, rec in items:
        rc = rec["returncode"] if rec["returncode"] is not None else rec["proc"].poll()
        runs[key] = {
            "pid": rec["proc"].pid,
            "mode": rec["mode"],
            "started": rec["started"],
            "alive": rc is None,
            "returncode": rc,
            "hasOutput": rec["mode"] == "capture",
            "lines": len(rec["output"]),
        }
    return {"workspace": str(WORKSPACE), "tools": tools, "runs": runs}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # 端口真被占用时应当失败，而不是和另一个实例同时监听
    allow_reuse_address = False

    def __init__(self, addr):
        self.token = secrets.token_urlsafe(24)
        self.page = HTML_FILE.read_text(encoding="utf-8").replace("__TOKEN__", self.token)
        super().__init__(addr, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def guard(self, post):
        host = "127.0.0.1:{}".format(self.server.server_port)
        if self.headers.get_all("Host") != [host]:
            raise InputError("Host 不匹配")
        origins = self.headers.get_all("Origin") or []
        want = "http://" + host
        if (post and origins != [want]) or (origins and origins != [want]):
            raise InputError("Origin 不匹配")
        if post and self.headers.get_all("X-Panel-Token") != [self.server.token]:
            raise InputError("令牌无效")

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            self.guard(False)
            if url.path == "/":
                return self.reply(200, self.server.page.encode("utf-8"),
                                  "text/html; charset=utf-8")
            if url.path == "/api/state":
                return self.reply(200, snapshot())
            if url.path == "/api/output":
                key = (parse_qs(url.query).get("id") or [""])[0]
                with LOCK:
                    rec = RUNNING.get(key)
                if rec is None:
                    raise InputError("没有该工具的运行记录")
                return self.reply(200, {"id": key, "lines": list(rec["output"])})
            raise InputError("未知路径")
        except InputError as exc:
            self.reply(400, {"error": str(exc)})
        except Exception:
            self.reply(500, {"error": "面板内部错误"})

    def do_POST(self):
        url = urlsplit(self.path)
        try:
            self.guard(True)
            if self.headers.get_all("Content-Type") != ["application/json"]:
                raise InputError("须为 application/json")
            lengths = self.headers.get_all("Content-Length") or []
            if len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > 65536:
                raise InputError("请求长度不合法")
            raw = self.rfile.read(int(lengths[0]))
            try:
                body = json.loads(raw or b"{}")
            except (ValueError, UnicodeError) as exc:
                raise InputError("JSON 无效") from exc
            if not isinstance(body, dict):
                raise InputError("JSON 须为对象")

            if url.path == "/api/run":
                key = body.get("id")
                if not isinstance(key, str):
                    raise InputError("缺少工具编号")
                with LOCK:
                    old = RUNNING.get(key)
                    if old is not None and old["proc"].poll() is None:
                        raise InputError("该工具已在运行")
                    RUNNING[key] = launch(key, body.get("args") or "")
                return self.reply(200, snapshot())
            if url.path == "/api/stop":
                key = body.get("id")
                if not isinstance(key, str):
                    raise InputError("缺少工具编号")
                return self.reply(200, {"message": stop(key)})
            if url.path == "/api/forget":
                key = body.get("id")
                with LOCK:
                    RUNNING.pop(key, None)
                return self.reply(200, snapshot())
            if url.path == "/api/shutdown":
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return self.reply(200, {"message": "已停止"})
            raise InputError("未知路径")
        except InputError as exc:
            self.reply(400, {"error": str(exc)})
        except Exception:
            self.reply(500, {"error": "面板内部错误"})


def main():
    ap = argparse.ArgumentParser(description="工具集图形面板（本地网页）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not HTML_FILE.is_file():
        print("缺少 panel_gui.html，无法启动", file=sys.stderr)
        return 1

    try:
        srv = Server(("127.0.0.1", args.port))
    except OSError as exc:
        print("端口 {} 不可用：{}".format(args.port, exc), file=sys.stderr)
        print("换一个：python panel_gui.py --port {}".format(args.port + 1), file=sys.stderr)
        return 1

    url = "http://127.0.0.1:{}".format(srv.server_port)
    print("面板：{}".format(url))
    print("关闭页面不会停止服务；结束请关掉本窗口或按 Ctrl+C。")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
