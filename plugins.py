"""
plugins.py

Plugin mechanism and built-in example plugins.
"""

import sys
import traceback
import uuid
import datetime
import re

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

# Blocked IPs set - add IPs here to enable blocking
BLOCKED_IPS = {
    # "127.0.0.1",
}


@plugin
def example_block_ip_plugin(request_info):
    """
    示例：按 IP 拦截。

    如果要启用，把 127.0.0.1 改成你想拦截的 IP（在 BLOCKED_IPS 集合中添加）。
    当前示例默认不拦截任何 IP。
    """
    client_ip = request_info["client"]["ip"]

    if client_ip in BLOCKED_IPS:
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



# =========================
# Bianlian Mock Plugin
# =========================

@plugin
def bianlian_mock_plugin(request_info):
    """
    Mock for DashScope video-generation / video-synthesis API.

    1. POST /api/v1/services/aigc/video-generation/video-synthesis
       - Body model == "happyhorse-1.0-video-edit"
       - Returns PENDING task with random task_id

    2. GET /api/v1/tasks/{task_id}
       - Returns SUCCEEDED result with mock video URL
    """
    path = request_info["url"]["path"]
    method = request_info["request"]["method"]

    # --- Submit task ---
    if method == "POST" and path == "/api/v1/services/aigc/video-generation/video-synthesis":
        body_json = request_info["body"].get("json")
        if not body_json:
            return None
        if body_json.get("model") != "happyhorse-1.0-video-edit":
            return None

        task_id = str(uuid.uuid4())
        return {
            "status": 200,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": {
                "request_id": task_id,
                "output": {
                    "task_id": task_id,
                    "task_status": "PENDING"
                }
            }
        }

    # --- Query task ---
    match = re.match(r"^/api/v1/tasks/([a-f0-9\-]+)$", path)
    if method == "GET" and match:
        task_id = match.group(1)
        now = datetime.datetime.now()
        submit_time = (now - datetime.timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        scheduled_time = (now - datetime.timedelta(minutes=1, seconds=59)).strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        end_time = (now - datetime.timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        return {
            "status": 200,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": {
                "request_id": str(uuid.uuid4()),
                "output": {
                    "task_id": task_id,
                    "task_status": "SUCCEEDED",
                    "submit_time": submit_time,
                    "scheduled_time": scheduled_time,
                    "end_time": end_time,
                    "orig_prompt": "让视频中的马头人身角色穿上图片中的条纹毛衣",
                    "video_url": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/mock-bianlian-output.mp4"
                },
                "usage": {
                    "duration": 13.24,
                    "input_video_duration": 6.62,
                    "output_video_duration": 6.62,
                    "video_count": 1,
                    "SR": 720
                }
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
