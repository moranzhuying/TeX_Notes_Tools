#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel_gui.py — 工具集面板（本地网页版，Qt 版的备用）

桌面窗口在 `panel_qt.py`，正常用那个。本文件只在没有 Qt 环境时兜底：
纯标准库、零依赖、浏览器界面。

启动规则、工具清单、运行状态全部来自 `panel_core`，与 Qt 版共用一套，
不在两处各写一遍。

    python panel_gui.py                 # 打开面板（127.0.0.1:7658）
    python panel_gui.py --port 7660
    python panel_gui.py --no-browser
"""
import argparse
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

TOOLS_ROOT = Path(__file__).resolve().parent
HTML_FILE = TOOLS_ROOT / "panel_gui.html"
DEFAULT_PORT = 7658

sys.path.insert(0, str(TOOLS_ROOT))
import panel_core as core  # noqa: E402

InputError = core.PanelError


def snapshot():
    runs = {}
    for tool in core.describe_tools():
        state = core.run_state(tool["id"])
        if state:
            runs[tool["id"]] = state
    return {"workspace": str(core.WORKSPACE),
            "tools": core.describe_tools(), "runs": runs}


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
                if core.record(key) is None:
                    raise InputError("没有该工具的运行记录")
                return self.reply(200, {"id": key, "lines": core.output_of(key)})
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
                state = core.run_state(key)
                if state and state["alive"]:
                    raise InputError("该工具已在运行")
                core.launch(key, body.get("args") or "")
                return self.reply(200, snapshot())
            if url.path == "/api/stop":
                key = body.get("id")
                if not isinstance(key, str):
                    raise InputError("缺少工具编号")
                return self.reply(200, {"message": core.stop(key)})
            if url.path == "/api/forget":
                core.forget(body.get("id"))
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
    ap = argparse.ArgumentParser(description="工具集面板（本地网页，Qt 版的备用）")
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
