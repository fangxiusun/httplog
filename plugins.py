"""
plugins.py

Plugin mechanism and built-in example plugins.
"""

import sys
import traceback


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
    body_text = request_info["body"].get("text") or ""

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


def run_plugins(request_info):
    """
    Execute plugins in order, return first non-None response.
    """
    for plugin_func in PLUGINS:
        try:
            result = plugin_func(request_info)
            if result is not None:
                return result
        except Exception as e:
            sys.stderr.write("[!] Plugin {} error: {}\n".format(plugin_func.__name__, e))
            traceback.print_exc()
    return None
