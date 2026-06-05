#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
httplog.py

一个简单的 HTTP 请求记录服务器。

功能：
1. 接收任意 HTTP 方法
2. 记录客户端 IP、端口、请求行、Header、Query、Body 等信息
3. /echo 返回请求信息
4. 支持插件机制，可根据请求信息自定义返回

运行：
    python httplog.py
    python httplog.py --host 0.0.0.0 --port 8080 --log httplog.jsonl

访问：
    curl http://127.0.0.1:8080/echo
    curl -X POST http://127.0.0.1:8080/test -H "Content-Type: application/json" -d '{"hello":"world"}'
"""

import argparse
import base64
import datetime
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


# =========================
# 全局配置
# =========================

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_LOG_FILE = "httplog.jsonl"

# 最大读取 Body 大小，防止超大请求撑爆内存
MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB


# =========================
# 插件机制
# =========================

PLUGINS = []


def plugin(func):
    """
    插件装饰器。

    插件函数接收 request_info，返回 None 或 response。

    返回 None：
        表示不处理，继续交给后续插件或默认逻辑。

    返回 dict：
        {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "body": "hello"
        }

    body 可以是：
        - str
        - bytes
        - dict/list，会自动转 JSON
    """
    PLUGINS.append(func)
    return func


# =========================
# 示例插件
# =========================

@plugin
def example_block_ip_plugin(request_info):
    """
    示例：按 IP 拦截。

    如果要启用，把 127.0.0.1 改成你想拦截的 IP。
    当前示例默认不拦截任何 IP。
    """
    blocked_ips = {
        # "127.0.0.1",
    }

    client_ip = request_info["client"]["ip"]

    if client_ip in blocked_ips:
        return {
            "status": 403,
            "headers": {
                "Content-Type": "application/json; charset=utf-8"
            },
            "body": {
                "ok": False,
                "message": "Forbidden by IP plugin",
                "client_ip": client_ip,
            }
        }

    return None


@plugin
def example_custom_path_plugin(request_info):
    """
    示例：自定义路径返回。

    请求：
        GET /hello

    返回：
        {"message": "hello from plugin"}
    """
    path = request_info["url"]["path"]

    if path == "/hello":
        return {
            "status": 200,
            "headers": {
                "Content-Type": "application/json; charset=utf-8"
            },
            "body": {
                "ok": True,
                "message": "hello from plugin"
            }
        }

    return None


@plugin
def example_body_keyword_plugin(request_info):
    """
    示例：根据 Body 内容自定义返回。

    如果 Body 文本中包含 ping，则返回 pong。
    """
    body_text = request_info["body"].get("text", "")

    if "ping" in body_text.lower():
        return {
            "status": 200,
            "headers": {
                "Content-Type": "application/json; charset=utf-8"
            },
            "body": {
                "ok": True,
                "message": "pong"
            }
        }

    return None


# =========================
# 工具函数
# =========================

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()


def safe_decode_body(body_bytes):
    """
    尝试把 body 解码为文本。
    如果失败，则返回 None。
    """
    if not body_bytes:
        return ""

    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return body_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    return None


def parse_json_body(body_text):
    """
    尝试将 body 文本解析为 JSON。
    """
    if not body_text:
        return None

    try:
        return json.loads(body_text)
    except Exception:
        return None


def json_dumps(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
        sort_keys=False
    )


def json_dumps_line(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False
    )


def normalize_headers(headers):
    """
    将 HTTP Headers 转成普通 dict。
    """
    result = {}
    for k, v in headers.items():
        result[k] = v
    return result


def make_response(status=200, headers=None, body=None):
    """
    构造统一响应对象。
    """
    return {
        "status": status,
        "headers": headers or {},
        "body": body if body is not None else ""
    }


# =========================
# HTTP Handler
# =========================

class HttpLogHandler(BaseHTTPRequestHandler):
    server_version = "HttpLog/1.0"

    def log_message(self, fmt, *args):
        """
        禁用 BaseHTTPRequestHandler 默认 stderr 日志。
        统一写入自己的日志文件。
        """
        if getattr(self.server, "verbose", False):
            sys.stderr.write(
                "%s - - [%s] %s\n" %
                (
                    self.client_address[0],
                    self.log_date_time_string(),
                    fmt % args
                )
            )

    def do_GET(self):
        self.handle_any_request()

    def do_POST(self):
        self.handle_any_request()

    def do_PUT(self):
        self.handle_any_request()

    def do_DELETE(self):
        self.handle_any_request()

    def do_OPTIONS(self):
        self.handle_any_request()

    def do_PATCH(self):
        self.handle_any_request()

    def do_HEAD(self):
        self.handle_any_request()

    def do_CONNECT(self):
        self.handle_any_request()

    def do_TRACE(self):
        self.handle_any_request()

    def handle_one_request(self):
        """
        保持父类行为。
        如果遇到未知 HTTP 方法，BaseHTTPRequestHandler 会找 do_xxx。
        为了接收任意方法，下面通过 __getattr__ 兜底。
        """
        return super().handle_one_request()

    def __getattr__(self, name):
        """
        兜底支持任意 HTTP 方法。

        例如：
            do_PROPFIND
            do_CUSTOM
        """
        if name.startswith("do_"):
            return self.handle_any_request
        raise AttributeError(name)

    def read_body(self):
        """
        读取请求 Body。
        """
        content_length = self.headers.get("Content-Length")

        if not content_length:
            return b""

        try:
            length = int(content_length)
        except ValueError:
            return b""

        if length <= 0:
            return b""

        if length > MAX_BODY_SIZE:
            body = self.rfile.read(MAX_BODY_SIZE)
            return body

        return self.rfile.read(length)

    def build_request_info(self):
        """
        构造完整请求信息。
        """
        client_ip, client_port = self.client_address

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query, keep_blank_values=True)

        headers = normalize_headers(self.headers)

        body_bytes = self.read_body()
        body_text = safe_decode_body(body_bytes)
        body_json = parse_json_body(body_text) if body_text is not None else None

        body_info = {
            "size": len(body_bytes),
            "text": body_text,
            "json": body_json,
            "base64": base64.b64encode(body_bytes).decode("ascii") if body_bytes else "",
            "truncated": len(body_bytes) >= MAX_BODY_SIZE,
        }

        request_info = {
            "time": now_iso(),
            "client": {
                "ip": client_ip,
                "port": client_port,
            },
            "server": {
                "host": self.server.server_address[0],
                "port": self.server.server_address[1],
            },
            "request": {
                "method": self.command,
                "requestline": self.requestline,
                "path_raw": self.path,
                "http_version": self.request_version,
            },
            "url": {
                "scheme": "http",
                "path": parsed.path,
                "query_string": parsed.query,
                "query": query,
                "fragment": parsed.fragment,
            },
            "headers": headers,
            "body": body_info,
        }

        return request_info

    def write_log(self, request_info):
        """
        写入日志文件，JSON Lines 格式。
        """
        log_file = self.server.log_file

        if log_file.endswith(".jsonl"):
            try:
                log_line = json_dumps_line(request_info)
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
                    f.write("\n")
            except Exception:
                traceback.print_exc()
        else:
            try:
                log_line = """
**************************************
%s
**************************************
                """ % json_dumps(request_info)
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
                    f.write("\n")
            except Exception:
                traceback.print_exc()

    def run_plugins(self, request_info):
        """
        运行插件。
        第一个返回非 None 的插件结果生效。
        """
        for func in PLUGINS:
            try:
                response = func(request_info)
                if response is not None:
                    return response
            except Exception as e:
                return make_response(
                    status=500,
                    headers={
                        "Content-Type": "application/json; charset=utf-8"
                    },
                    body={
                        "ok": False,
                        "message": "Plugin error",
                        "plugin": getattr(func, "__name__", str(func)),
                        "error": str(e),
                    }
                )

        return None

    def handle_echo(self, request_info):
        """
        /echo 通用 URL。
        返回格式化 JSON。
        """
        return make_response(
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            body={
                "ok": True,
                "echo": request_info,
            }
        )

    def handle_default(self, request_info):
        """
        默认返回。
        """
        return make_response(
            status=200,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store",
            },
            body={
                "ok": True,
                "message": "request logged",
                "method": request_info["request"]["method"],
                "path": request_info["url"]["path"],
                "client": request_info["client"],
            }
        )

    def send_custom_response(self, response):
        """
        发送响应。
        """
        status = int(response.get("status", 200))
        headers = response.get("headers") or {}
        body = response.get("body", "")

        if isinstance(body, (dict, list)):
            body_bytes = json_dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = str(body).encode("utf-8")
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        headers.setdefault("Content-Length", str(len(body_bytes)))
        headers.setdefault("Access-Control-Allow-Origin", "*")
        headers.setdefault("Access-Control-Allow-Methods", "*")
        headers.setdefault("Access-Control-Allow-Headers", "*")

        self.send_response(status)

        for k, v in headers.items():
            self.send_header(k, v)

        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(body_bytes)

    def handle_any_request(self):
        """
        处理任意请求。
        """
        try:
            request_info = self.build_request_info()

            # 先写日志
            self.write_log(request_info)

            path = request_info["url"]["path"]

            # 内置 /echo
            if path == "/echo":
                response = self.handle_echo(request_info)
                self.send_custom_response(response)
                return

            # 插件处理
            plugin_response = self.run_plugins(request_info)
            if plugin_response is not None:
                self.send_custom_response(plugin_response)
                return

            # 默认处理
            response = self.handle_default(request_info)
            self.send_custom_response(response)

        except Exception as e:
            traceback.print_exc()
            response = make_response(
                status=500,
                headers={
                    "Content-Type": "application/json; charset=utf-8"
                },
                body={
                    "ok": False,
                    "message": "internal server error",
                    "error": str(e),
                }
            )
            self.send_custom_response(response)


# =========================
# Server
# =========================

class HttpLogServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, log_file, verbose=False):
        super().__init__(server_address, RequestHandlerClass)
        self.log_file = log_file
        self.verbose = verbose


def main():
    parser = argparse.ArgumentParser(
        description="HTTP request logger server"
    )

    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"listen host, default: {DEFAULT_HOST}"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"listen port, default: {DEFAULT_PORT}"
    )

    parser.add_argument(
        "--log",
        default=DEFAULT_LOG_FILE,
        help=f"log file path, default: {DEFAULT_LOG_FILE}"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print access log to stderr"
    )

    args = parser.parse_args()

    server = HttpLogServer(
        server_address=(args.host, args.port),
        RequestHandlerClass=HttpLogHandler,
        log_file=args.log,
        verbose=args.verbose,
    )

    print(f"[+] HttpLog server listening on http://{args.host}:{args.port}")
    print(f"[+] Log file: {args.log}")
    print("[+] Echo URL: /echo")
    print("[+] Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Stopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
