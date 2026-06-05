"""
utils.py

Shared utility functions for httplog.
"""

import datetime


# =========================
# Global config
# =========================

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_LOG_FILE = "httplog.jsonl"  # auto split by day: httplog-2025-06-05.jsonl
DEFAULT_PID_FILE = "httplog.pid"

# Max body size to read, prevent OOM
MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB

# Max unique entries in stats counters (paths, ips) to prevent memory bloat
MAX_STATS_ENTRIES = 10000

import json
import os
import re


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()


def format_daily_log_path(log_pattern):
    """
    daily log path with strftime support.

    1. pattern with strftime placeholders (%Y, %m, %d): format directly
    2. no placeholders: insert -YYYY-MM-DD before file extension

    examples:
        httplog.jsonl              -> httplog-2025-06-05.jsonl
        logs/httplog.jsonl         -> logs/httplog-2025-06-05.jsonl
        httplog-%Y%m.jsonl         -> httplog-202506.jsonl
    """
    now = datetime.datetime.now()

    # strftime placeholders present: format directly
    if '%Y' in log_pattern or '%m' in log_pattern or '%d' in log_pattern:
        return now.strftime(log_pattern)

    # no placeholders: insert date before extension
    date_str = now.strftime('%Y-%m-%d')
    dot_idx = log_pattern.rfind('.')
    if dot_idx > 0:
        return log_pattern[:dot_idx] + '-' + date_str + log_pattern[dot_idx:]
    return log_pattern + '-' + date_str




def discover_logs(log_pattern):
    """
    scan log directory and find all log files matching the pattern.
    returns list of dict sorted by date desc: [{name, path, size, mtime}]
    """
    log_pattern = log_pattern.replace(chr(92), '/')

    # extract base dir from pattern
    parts = log_pattern.rsplit('/', 1)
    if len(parts) == 2:
        log_dir = parts[0]
        filename_pattern = parts[1]
    else:
        log_dir = '.'
        filename_pattern = log_pattern

    if not os.path.isdir(log_dir):
        return []

    # build a regex from the filename pattern to match date-based files
    has_strftime = '%Y' in filename_pattern or '%m' in filename_pattern or '%d' in filename_pattern

    if has_strftime:
        regex = re.escape(filename_pattern)
        regex = regex.replace(re.escape('%Y'), r'(\d{4})')
        regex = regex.replace(re.escape('%m'), r'(\d{2})')
        regex = regex.replace(re.escape('%d'), r'(\d{2})')
        regex = '^' + regex + '$'
    else:
        base, ext = os.path.splitext(filename_pattern)
        regex = '^' + re.escape(base) + r'-\d{4}-\d{2}-\d{2}' + re.escape(ext) + '$'

    results = []
    try:
        for entry in os.scandir(log_dir):
            if entry.is_file() and re.match(regex, entry.name):
                stat = entry.stat()
                results.append({
                    'name': entry.name,
                    'path': entry.path,
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                    'mtime_str': datetime.datetime.fromtimestamp(
                        stat.st_mtime
                    ).strftime('%Y-%m-%d %H:%M:%S'),
                })
    except OSError:
        pass

    results.sort(key=lambda x: x['mtime'], reverse=True)
    return results


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
    构造统一响应结构。
    """
    return {
        "status": status,
        "headers": headers or {},
        "body": body,
    }
