# httplog

一个轻量级的 HTTP 请求记录服务器，基于 Python 标准库实现，零依赖。

接收任意 HTTP 请求，将完整的请求信息记录到 JSONL 日志文件，并支持通过插件机制自定义响应。

## 功能特性

- **全方法支持** — 接收 GET、POST、PUT、DELETE 等任意 HTTP 方法
- **详细日志记录** — 记录客户端 IP、端口、请求行、Headers、Query 参数、Body 等信息
- **JSONL 日志格式** — 每行一条 JSON 记录，便于 grep、jq 等工具处理
- **按日分文件** — 自动按天生成日志文件，支持 strftime 路径模板
- **内置 /echo 接口** — 返回完整的请求信息，方便调试
- **插件机制** — 通过 @plugin 装饰器自定义路由和响应逻辑
- **守护进程模式** — 支持 --daemon 后台运行，无需手动 nohup
- **健康检查** — /healthz 端点，返回服务状态、运行时间、请求计数
- **请求统计** — /stats 仪表盘，展示方法分布、状态码、热门路径、来源 IP Top N
- - **在线日志浏览** — 内置 Web 日志查看器，支持文件列表、在线浏览、分页、下载
- **CORS 支持** — 默认开启跨域，适合前端联调
- **多线程处理** — 基于 ThreadingHTTPServer，支持并发请求
- **TLS/HTTPS** — 自动生成自签名证书，支持 HTTPS 服务

## 快速开始

### 运行

`bash
# 默认监听 0.0.0.0:8080
python httplog.py

# 自定义配置
python httplog.py --host 127.0.0.1 --port 9000 --log mylog.jsonl

# 开启详细输出（请求信息打印到 stderr）
python httplog.py --verbose

# 启用 HTTPS（自动生成自签名证书）
python httplog.py --https

# 后台守护进程模式
python httplog.py --daemon
python httplog.py --daemon --port 9000 --log mylog.jsonl
python httplog.py --daemon --pid /var/run/httplog.pid

# 停止守护进程
python httplog.py --stop --pid httplog.pid

# 健康检查
curl http://127.0.0.1:8080/healthz

# 请求统计仪表盘
# browser: http://127.0.0.1:8080/stats

# 启动日志浏览器（访问 /logs）
python httplog.py --log-viewer /logs
`

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --host | 0.0.0.0 | 监听地址 |
| --port | 8080 | 监听端口 |
| --log | httplog.jsonl | 日志文件路径 |
| --verbose | 关闭 | 将访问日志输出到 stderr |
| --daemon | 关闭 | 后台守护进程模式运行 |
| --pid | httplog.pid | PID 文件路径（配合 --daemon/--stop 使用） |
| --stop | - | 停止指定的守护进程（需配合 --pid 使用） |
| --log-viewer | 关闭 | 启用内置 Web 日志浏览器，指定访问路径，如 /logs |

### 测试请求

`bash
# 查看请求回显
curl http://127.0.0.1:8080/echo

# 发送 POST 请求
curl -X POST http://127.0.0.1:8080/test \
  -H "Content-Type: application/json" \
  -d '{"hello": "world"}'

# 测试插件路由
curl http://127.0.0.1:8080/hello

# 测试 Body 关键字插件
curl -X POST http://127.0.0.1:8080/test \
  -H "Content-Type: text/plain" \
  -d 'ping me'
`


## 后台运行（守护进程）

使用 --daemon 参数可将服务转为后台守护进程，无需手动 nohup：
ohup：

```bash
# 启动守护进程
python httplog.py --daemon

# 自定义配置 + 守护进程
python httplog.py --daemon --host 0.0.0.0 --port 9000 --log /var/log/httplog.jsonl

# 指定 PID 文件路径
python httplog.py --daemon --pid /var/run/httplog.pid

# 查看守护进程状态
cat httplog.pid

# 停止守护进程
python httplog.py --stop --pid httplog.pid

# 健康检查
curl http://127.0.0.1:8080/healthz

# 请求统计仪表盘
# browser: http://127.0.0.1:8080/stats

# 启动日志浏览器（访问 /logs）
python httplog.py --log-viewer /logs
```

守护进程的 stdout/stderr 输出会保存到 {pid文件路径}.stdout，例如 httplog.pid.stdout。

### 工作原理

- **Linux/macOS**: 采用经典 double-fork 方式脱离终端，重定向标准输入输出到文件
- **Windows**: 通过 CREATE_NO_WINDOW 标志启动无窗口后台子进程，父进程退出

## 日志格式

日志自动按天分文件，每个文件名包含日期：

`
httplog-2026-06-05.jsonl
httplog-2026-06-06.jsonl
httplog-2026-06-07.jsonl
`

支持 strftime 路径模板：

| --log 参数 | 实际文件 |
|------|------|
| httplog.jsonl | httplog-2026-06-05.jsonl |
| logs/httplog.jsonl | logs/httplog-2026-06-05.jsonl |
| httplog-%Y%m.jsonl | httplog-202606.jsonl |
| /var/log/%Y/%m/httplog.jsonl | /var/log/2026/06/httplog.jsonl |

目录不存在时会自动创建。

每条日志为一行 JSON，记录完整请求信息：

`json
{
  "timestamp": "2025-01-01T12:00:00+08:00",
  "client": {
    "ip": "127.0.0.1",
    "port": 54321
  },
  "request": {
    "method": "POST",
    "version": "HTTP/1.1"
  },
  "url": {
    "path": "/test",
    "query": {},
    "raw_query": "",
    "fragment": ""
  },
  "headers": {
    "Content-Type": "application/json",
    "User-Agent": "curl/7.68.0"
  },
  "body": {
    "text": "{\"hello\": \"world\"}",
    "json": {"hello": "world"}
  }
}
`

Body 字段说明：
- text — 原始文本内容（尝试 UTF-8、GB18030、Latin-1 解码）
- json — 如果是合法 JSON 则自动解析，否则为 
ull
- base64 — 当文本解码失败时，以 Base64 编码存储

## 插件开发

使用 @plugin 装饰器注册插件函数。插件按注册顺序依次执行，第一个返回非 None 的插件决定响应。

`python
@plugin
def my_plugin(request_info):
    """自定义插件示例"""
    path = request_info["url"]["path"]

    if path == "/health":
        return {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "body": {"ok": True}
        }

    return None  # 不处理，交给下一个插件
`

### 响应格式

`python
{
    "status": 200,                      # HTTP 状态码
    "headers": {"Content-Type": "..."}, # 响应头
    "body": "..."                       # 响应体：str / bytes / dict（自动转 JSON）
}
`

### request_info 结构

插件接收的 
equest_info 包含以下字段：

| 字段 | 说明 |
|------|------|
| client.ip | 客户端 IP |
| client.port | 客户端端口 |
| 
equest.method | HTTP 方法 |
| 
equest.version | HTTP 版本 |
| url.path | 请求路径 |
| url.query | 查询参数（dict） |
| url.raw_query | 原始查询字符串 |
| headers | 请求头（dict） |
| body.text | Body 文本 |
| body.json | Body JSON 解析结果 |
| body.content_type | Content-Type |

### 内置示例插件

代码中包含三个示例插件：

1. **IP 拦截** (example_block_ip_plugin) — 按 IP 地址拦截请求
2. **自定义路径** (example_custom_path_plugin) — GET /hello 返回自定义响应
3. **Body 关键字** (example_body_keyword_plugin) — Body 包含 "ping" 时返回 "pong"

示例插件默认不拦截请求，可直接修改 blocked_ips 集合启用 IP 拦截。

## 项目结构

`
httplog/
└── httplog.py      # 主入口：服务器、请求处理器、统计、main()
    ├── daemon.py       # 守护进程：fork/CREATE_NO_WINDOW/PID管理
    ├── viewer.py       # Web日志浏览器：文件列表、在线浏览、下载、统计仪表盘
    ├── plugins.py      # 插件机制：@装饰器 + 示例插件
    └── utils.py        # 工具函数：时间、日志路径、JSON、Body解析、全局配置
`

## 依赖

无外部依赖，仅使用 Python 标准库：

- http.server — HTTP 服务器（ThreadingHTTPServer）
- json — JSON 处理
- argparse — 命令行解析
- threading — 线程安全锁
- collections — 统计计数器
- re / html — 正则表达式 / XSS 转义
- os / signal / subprocess — 守护进程管理

要求 Python 3.7+。

## 使用场景

- **API 调试** — 查看客户端发送的完整请求信息
- **Webhook 接收** — 接收并记录第三方回调请求
- **前端开发** — 作为 mock 服务器，支持 CORS 跨域
- **请求回放** — 从 JSONL 日志中提取请求数据进行分析
- **安全测试** — 通过插件实现简单的访问控制


## 在线日志浏览器

启动时添加 --log-viewer 参数，即可通过浏览器查看日志：

`ash
python httplog.py --log-viewer /logs
`

访问 http://127.0.0.1:8080/logs，即可看到日志文件列表。

### 功能

- **文件列表** — 自动扫描日志目录，显示文件名、修改时间、文件大小
- **在线浏览** — 点击文件名查看日志内容，JSON 语法高亮
- **分页导航** — 支持 First/Prev/Next/Last 分页，每页默认 200 行，最大 2000 行
- **下载文件** — 支持将日志文件下载到本地
- **安全校验** — 防止路径穿越攻击，仅访问日志目录内的文件

### 访问地址

| 地址 | 说明 |
|------|------|
| /logs | 日志文件列表 |
| /logs?file=httplog-2026-06-05.jsonl | 在线浏览指定日志 |
| /logs?file=httplog-2026-06-05.jsonl&offset=0&limit=100 | 分页查看 |
| /logs?file=httplog-2026-06-05.jsonl&download=1 | 下载日志文件 |


## Built-in Endpoints

| Endpoint | Description |
|------|------|
| /echo | Returns full request info as JSON |
| /healthz | Health check: {"ok":true, "uptime":"5m 30s", "requests":1234, "errors":0} |
| /stats | Stats dashboard (requires --log-viewer) |

### /stats Dashboard

Access /stats to view:

- **Uptime** - server running time
- **Total Requests** - total request count
- **Errors (5xx)** - server error count
- **Unique IPs** - unique client count
- **Method Distribution** - GET/POST/PUT etc.
- **Status Codes** - 200/404/500 etc.
- **Top Paths** - top 10 most visited paths
- **Top IPs** - top 10 most active clients

## License

MIT
