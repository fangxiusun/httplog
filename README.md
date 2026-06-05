# httplog

一个轻量级的 HTTP 请求记录服务器，基于 Python 标准库实现，零依赖。

接收任意 HTTP 请求，将完整的请求信息记录到 JSONL 日志文件，并支持通过插件机制自定义响应。

## 功能特性

- **全方法支持** — 接收 GET、POST、PUT、DELETE 等任意 HTTP 方法
- **详细日志记录** — 记录客户端 IP、端口、请求行、Headers、Query 参数、Body 等信息
- **JSONL 日志格式** — 每行一条 JSON 记录，便于 grep、jq 等工具处理
- **内置 /echo 接口** — 返回完整的请求信息，方便调试
- **插件机制** — 通过 @plugin 装饰器自定义路由和响应逻辑
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
`

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| --host | 0.0.0.0 | 监听地址 |
| --port | 8080 | 监听端口 |
| --log | httplog.jsonl | 日志文件路径 |
| --verbose | 关闭 | 将访问日志输出到 stderr |
| --https | 关闭 | 启用 HTTPS（自签名证书） |

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

## 日志格式

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
└── httplog.py      # 单文件实现，包含服务器、处理器、插件系统
`

## 依赖

无外部依赖，仅使用 Python 标准库：

- http.server — HTTP 服务器
- json — JSON 处理
- argparse — 命令行解析
- datetime — 时间戳
- ssl — HTTPS 支持
- 	hreading — 多线程（通过 ThreadingHTTPServer）

要求 Python 3.7+。

## 使用场景

- **API 调试** — 查看客户端发送的完整请求信息
- **Webhook 接收** — 接收并记录第三方回调请求
- **前端开发** — 作为 mock 服务器，支持 CORS 跨域
- **请求回放** — 从 JSONL 日志中提取请求数据进行分析
- **安全测试** — 通过插件实现简单的访问控制

## License

MIT
