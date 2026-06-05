"""
viewer.py

Built-in web log viewer: file list, online browsing, download.
"""

import base64
import html
import os
import re

from utils import discover_logs, make_response


class LogViewerHandler:
    """
    built-in log viewer: file list, online browsing, download.
    """

    def handle_request(self, handler, log_pattern, base_path):
        """Route incoming request to the appropriate viewer handler."""
        from urllib.parse import urlparse, parse_qs
        import sys

        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        sub_path = parsed.path[len(base_path):]

        try:
            if sub_path in ("", "/"):
                if "file" in query:
                    filename = query['file'][0]
                    if query.get('download'):
                        resp = self.handle_download(handler, log_pattern, filename)
                    else:
                        resp = self.handle_view(handler, log_pattern, filename, query)
                else:
                    resp = self.handle_list(handler, log_pattern)
            elif sub_path.startswith("/stats"):
                resp = self.handle_stats(handler)
            elif sub_path.startswith("/download/"):
                filename = sub_path[len("/download/"):]
                resp = self.handle_download(handler, log_pattern, filename)
            else:
                resp = make_response(404, {'Content-Type': 'text/html; charset=utf-8'},
                                    self._err(base_path, 'Page not found'))
        except Exception as e:
            sys.stderr.write("[!] Viewer error: {}\\n".format(e))
            import traceback
            traceback.print_exc()
            resp = make_response(500, {'Content-Type': 'text/html; charset=utf-8'},
                                 self._err(base_path, "Internal error: " + str(e)))

        # Send response via the HTTP handler
        self._send(handler, resp)

    def _send(self, handler, resp):
        """Send a make_response dict via the HTTP handler."""
        status = resp["status"]
        headers = resp["headers"]
        body = resp.get("body")

        handler.send_response(status)
        for k, v in headers.items():
            handler.send_header(k, v)

        if isinstance(body, bytes):
            body_bytes = body
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = b""

        handler.send_header("Content-Length", str(len(body_bytes)))
        handler.end_headers()
        if body_bytes:
            handler.wfile.write(body_bytes)


    CSS = """
    <style>
      * { margin:0; padding:0; box-sizing:border-box; }
      body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
             background:#f0f2f5; color:#1a1a2e; line-height:1.6; }
      .header { background:linear-gradient(135deg,#1a1a2e,#16213e); color:#fff;
                padding:18px 24px; }
      .header h1 { font-size:20px; font-weight:600; }
      .header a { color:#8ecae6; text-decoration:none; margin-left:16px; font-size:14px; }
      .header a:hover { text-decoration:underline; }
      .container { max-width:1200px; margin:24px auto; padding:0 16px; }
      .card { background:#fff; border-radius:8px; box-shadow:0 1px 3px rgba(0,0,0,.08);
              overflow:hidden; margin-bottom:20px; }
      table { width:100%; border-collapse:collapse; }
      th { background:#f8f9fa; text-align:left; padding:10px 16px; font-size:13px;
           color:#666; border-bottom:1px solid #eee; }
      td { padding:10px 16px; border-bottom:1px solid #f0f0f0; font-size:14px; }
      tr:hover td { background:#f8fbff; }
      td.size { text-align:right; font-family:monospace; color:#555; }
      .btn { display:inline-block; padding:4px 12px; border-radius:4px; font-size:12px;
             text-decoration:none; border:none; cursor:pointer; }
      .btn-view { background:#e8f4f8; color:#0077b6; }
      .btn-view:hover { background:#d0ecf4; }
      .btn-dl { background:#e8f5e9; color:#2e7d32; margin-left:6px; }
      .btn-dl:hover { background:#c8e6c9; }
      .btn-nav { background:#1a1a2e; color:#fff; padding:6px 16px; font-size:13px; }
      .btn-nav:hover { background:#16213e; }
      .btn-nav.disabled { background:#aaa; cursor:default; pointer-events:none; opacity:0.5; }
      .log-box { background:#1a1a2e; color:#e0e0e0; padding:16px; font-family:"Cascadia Code",
                 "Fira Code",Consolas,monospace; font-size:13px; line-height:1.7;
                 overflow-x:auto; white-space:pre-wrap; word-break:break-all;
                 max-height:75vh; overflow-y:auto; }
      .log-box .ln { color:#555; user-select:none; margin-right:12px; }
      .log-box .jk { color:#8ecae6; }
      .log-box .js { color:#a7c957; }
      .log-box .jn { color:#f4a261; }
      .log-box .jb { color:#e76f51; }
      .log-box .jx { color:#999; }
      .nav-bar { display:flex; justify-content:space-between; align-items:center;
                 padding:12px 16px; background:#f8f9fa; border-bottom:1px solid #eee; }
      .nav-bar .info { font-size:13px; color:#666; }
      .empty { text-align:center; padding:60px 20px; color:#999; }
      .badge { display:inline-block; background:#e8f4f8; color:#0077b6; padding:2px 8px;
               border-radius:4px; font-size:12px; margin-left:8px; }
      .json-btn { display:inline-block; margin-left:8px; padding:1px 5px;
                  font-size:11px; color:#8ecae6; cursor:pointer; border:1px solid #333;
                  border-radius:3px; background:transparent; font-family:inherit; }
      .json-btn:hover { background:#2a2a3e; }
      .json-modal { display:none; position:fixed; top:0; left:0; width:100vw; height:100vh;
                    background:rgba(0,0,0,.6); z-index:1000; justify-content:center;
                    align-items:center; }
      .json-modal.show { display:flex; }
      .json-modal-box { background:#1a1a2e; color:#e0e0e0; border-radius:8px;
                         max-width:900px; width:90vw; max-height:85vh; overflow:auto;
                         padding:20px; font-family:"Cascadia Code","Fira Code",Consolas,monospace;
                         font-size:13px; line-height:1.6; white-space:pre-wrap; word-break:break-all;
                         box-shadow:0 8px 32px rgba(0,0,0,.4); position:relative; }
      .json-modal-close { position:sticky; top:0; float:right; background:none; border:none;
                           color:#8ecae6; font-size:18px; cursor:pointer; padding:4px 8px; }
      .json-modal-close:hover { color:#fff; }
    </style>
    """

    @staticmethod
    def _hl(text):
        """simple JSON syntax highlighting."""
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r'"([^"]*?)"(\s*:)', r'<span class="jk">"\1"</span>\2', text)
        text = re.sub(r':\s*"(.*?)"', r': <span class="js">"\1"</span>', text)
        text = re.sub(r':\s*(\d+\.?\d*)', r': <span class="jn">\1</span>', text)
        text = re.sub(r':\s*(true|false)', r': <span class="jb">\1</span>', text)
        text = re.sub(r':\s*(null)', r': <span class="jx">\1</span>', text)
        return text

    @staticmethod
    def _fsize(size):
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return "{:.1f} {}".format(size, unit) if unit != "B" else "{} B".format(size)
            size /= 1024
        return "{:.1f} TB".format(size)

    def handle_list(self, handler, log_pattern):
        """file list page."""
        logs = discover_logs(log_pattern)
        bp = handler.server.log_viewer_path

        rows = ""
        for log in logs:
            rows += (
                "<tr>"
                '<td><a href="' + html.escape(bp, quote=True) + '?file=' + html.escape(log["name"]) + '">' + html.escape(log["name"]) + '</a></td>'
                "<td>" + log["mtime_str"] + "</td>"
                '<td class="size">' + self._fsize(log["size"]) + "</td>"
                "<td>"
                '  <a class="btn btn-view" href="' + html.escape(bp, quote=True) + '?file=' + log["name"] + '">View</a>'
                '  <a class="btn btn-dl" href="' + html.escape(bp, quote=True) + '?file=' + html.escape(log["name"]) + '&download=1">Download</a>'
                "</td></tr>"
            )

        if not rows:
            body = '<div class="empty">No log files found.<br>Logs will appear here after requests are recorded.</div>'
        else:
            body = (
                '<div class="card"><table>'
                "<thead><tr><th>File</th><th>Last Modified</th><th>Size</th><th>Actions</th></tr></thead>"
                "<tbody>" + rows + "</tbody></table></div>"
            )

        page = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>HttpLog - Log Files</title>" + self.CSS + "</head><body>"
            '<div class="header"><h1>HttpLog <span class="badge">' + str(len(logs)) + ' file(s)</span></h1>'
            '<a href="' + html.escape(bp, quote=True) + '">Refresh</a> <a href="/echo">Echo</a></div>'
            '<div class="container">' + body + '</div></body></html>'
        )
        return make_response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, page)

    def handle_view(self, handler, log_pattern, filename, query):
        """log viewer page with pagination."""
        bp = handler.server.log_viewer_path
        filepath = self._resolve(log_pattern, filename)

        if not filepath or not os.path.isfile(filepath):
            return make_response(404, {"Content-Type": "text/html; charset=utf-8"},
                                  self._err(bp, "Log file not found: " + filename))

        # pagination
        limit = min(int(query.get("limit", ["200"])[0]), 2000)
        offset = max(int(query.get("offset", ["0"])[0]), 0)

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except Exception as e:
            return make_response(500, {"Content-Type": "text/html; charset=utf-8"},
                                  self._err(bp, "Error reading file: " + str(e)))

        total = len(all_lines)
        lines = all_lines[offset:offset + limit]

        rendered = ""
        for i, line in enumerate(lines):
            ln = offset + i + 1
            hl = self._hl(line.rstrip())
            raw = line.rstrip()
            encoded = base64.b64encode(raw.encode('utf-8')).decode('ascii')
            rendered += '<span class="ln">' + str(ln).rjust(6) + '</span>' + hl + '<button class="json-btn" data-b64="' + encoded + '" onclick="showJSON(this)">{}</button>' + "\n"

        has_prev = offset > 0
        has_next = offset + limit < total
        prev_off = max(0, offset - limit)
        next_off = offset + limit
        last_off = max(0, total - limit)

        def nav_btn(label, off, disabled):
            cls = "btn btn-nav disabled" if disabled else "btn btn-nav"
            return '<a class="' + cls + '" href="' + html.escape(bp, quote=True) + '?file=' + filename + '&offset=' + str(off) + '&limit=' + str(limit) + '">' + label + '</a>'

        showing_end = min(offset + limit, total)
        nav = (
            '<div class="nav-bar">'
            '<span class="info">Lines ' + str(offset+1) + '-' + str(showing_end) + ' of ' + str(total) + '</span>'
            "<div>"
            + nav_btn("First", 0, not has_prev)
            + nav_btn("Prev", prev_off, not has_prev)
            + nav_btn("Next", next_off, not has_next)
            + nav_btn("Last", last_off, not has_next)
            + ' <a class="btn btn-dl" href="' + html.escape(bp, quote=True) + '?file=' + filename + '&download=1">Download</a>'
            + "</div></div>"
        )

        page = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>HttpLog - " + html.escape(filename) + "</title>" + self.CSS + "</head><body>"
            '<div class="header"><h1>' + html.escape(filename) + '</h1>'
            '<a href="' + html.escape(bp, quote=True) + '">Back to list</a> <a href="/echo">Echo</a></div>'
            '<div class="container"><div class="card">' + nav + '<div class="log-box">' + rendered + '</div></div></div>'
            '<div id="jsonModal" class="json-modal" onclick="if(event.target===this)this.classList.remove(\'show\')">'
            '<div class="json-modal-box">'
            '<button class="json-modal-close" onclick="this.parentElement.parentElement.classList.remove(\'show\')">X</button>'
            '<div id="jsonModalContent"></div></div></div>'
            '<script>'
            'function showJSON(el){'
            '  var b64=el.getAttribute("data-b64");'
            '  if(!b64) return;'
            '  try{'
            '    var decoded=atob(b64);var raw=new TextDecoder().decode(Uint8Array.from(decoded,c=>c.charCodeAt(0)));'
            '    try{'
            '      var obj=JSON.parse(raw);'
            '      document.getElementById("jsonModalContent").textContent=JSON.stringify(obj,null,2);'
            '    }catch(e){'
            '      document.getElementById("jsonModalContent").textContent="JSON parse error: "+e.message+"\\n\\nRaw:\\n"+raw;'
            '    }'
            '  }catch(e2){'
            '    document.getElementById("jsonModalContent").textContent="Decode error: "+e2.message;'
            '  }'
            '  document.getElementById("jsonModal").classList.add("show");'
            '}'
            '</script>'
            "</body></html>"
        )
        return make_response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, page)

    def handle_download(self, handler, log_pattern, filename):
        """download a log file."""
        filepath = self._resolve(log_pattern, filename)

        if not filepath or not os.path.isfile(filepath):
            return make_response(404, {"Content-Type": "application/json"},
                                  {"ok": False, "message": "file not found"})

        try:
            with open(filepath, "rb") as f:
                data = f.read()
            return make_response(200, {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment;filename="' + filename + '"',
                "Content-Length": str(len(data)),
            }, data)
        except Exception as e:
            return make_response(500, {"Content-Type": "application/json"},
                                  {"ok": False, "message": str(e)})


    def handle_stats(self, handler):
        """Stats dashboard page."""
        bp = handler.server.log_viewer_path
        stats = handler.server.stats

        # summary cards
        summary = (
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px;">'
            + self._stat_card("Uptime", stats.uptime_str(), "#1a1a2e")
            + self._stat_card("Total Requests", str(stats.total), "#0077b6")
            + self._stat_card("Errors (5xx)", str(stats.errors), "#e63946")
            + self._stat_card("Unique IPs", str(len(stats.ips)), "#2a9d8f")
            + '</div>'
        )

        # method distribution
        method_rows = ""
        for method, count in stats.methods.most_common(10):
            pct = count * 100 // stats.total if stats.total else 0
            method_rows += self._bar_row(html.escape(method), count, pct)
        methods_table = self._card("Method Distribution", method_rows)

        # status code distribution
        status_rows = ""
        for code, count in stats.status_codes.most_common(10):
            pct = count * 100 // stats.total if stats.total else 0
            color = "#2a9d8f" if code < 400 else "#f4a261" if code < 500 else "#e63946"
            status_rows += self._bar_row(str(code), count, pct, color)
        status_table = self._card("Status Codes", status_rows)

        # top paths
        path_rows = ""
        for path, count in stats.paths.most_common(10):
            pct = count * 100 // stats.total if stats.total else 0
            path_rows += self._bar_row(html.escape(path), count, pct, "#457b9d")
        paths_table = self._card("Top Paths", path_rows)

        # top IPs
        ip_rows = ""
        for ip, count in stats.ips.most_common(10):
            pct = count * 100 // stats.total if stats.total else 0
            ip_rows += self._bar_row(html.escape(ip), count, pct, "#6d6875")
        ips_table = self._card("Top IPs", ip_rows)

        page = (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>HttpLog - Stats</title>" + self.CSS + self._stats_css()
            + "</head><body>"
            '<div class="header"><h1>Request Statistics</h1>'
            '<a href="' + html.escape(bp, quote=True) + '">Log Files</a> <a href="/echo">Echo</a></div>'
            '<div class="container">' + summary
            + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">'
            + methods_table + status_table + paths_table + ips_table
            + '</div></div></body></html>'
        )
        return make_response(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, page)

    @staticmethod
    def _stat_card(label, value, color):
        return (
            '<div style="background:#fff;border-radius:8px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center;">'
            '<div style="font-size:28px;font-weight:700;color:' + color + ';">' + value + '</div>'
            '<div style="font-size:13px;color:#888;margin-top:4px;">' + label + '</div></div>'
        )

    def _card(self, title, rows):
        if not rows:
            rows = '<div style="padding:20px;text-align:center;color:#999;">No data</div>'
        return (
            '<div class="card" style="margin-bottom:0;">'
            '<div style="padding:12px 16px;font-weight:600;font-size:14px;border-bottom:1px solid #eee;">'
            + title + '</div>' + rows + '</div>'
        )

    @staticmethod
    def _bar_row(label, count, pct, color="#0077b6"):
        return (
            '<div style="padding:8px 16px;display:flex;align-items:center;gap:10px;">'
            '<span style="width:120px;font-size:13px;font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
            + html.escape(str(label)) + '</span>'
            '<div style="flex:1;background:#f0f0f0;border-radius:4px;height:18px;overflow:hidden;">'
            '<div style="width:' + str(min(pct, 100)) + '%;background:' + color + ';height:100%;border-radius:4px;"></div></div>'
            '<span style="width:60px;text-align:right;font-size:13px;font-family:monospace;color:#555;">'
            + str(count) + '</span></div>'
        )

    @staticmethod
    def _stats_css():
        return """<style>
      @media (max-width:768px) {
        .container > div[style*="grid-template-columns:1fr 1fr"] { grid-template-columns:1fr !important; }
      }
    </style>"""

    def _resolve(self, log_pattern, filename):
        """resolve log file path, prevent path traversal."""
        if ".." in filename or "/" in filename or chr(92) in filename:
            return None
        parts = log_pattern.replace(chr(92), "/").rsplit("/", 1)
        log_dir = parts[0] if len(parts) == 2 else "."
        return os.path.normpath(os.path.join(log_dir, filename))

    def _err(self, bp, msg):
        return (
            '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Error</title>'
            + self.CSS + '</head><body>'
            '<div class="header"><h1>HttpLog</h1><a href="' + html.escape(bp, quote=True) + '">Back</a></div>'
            '<div class="container"><div class="card"><div class="empty">' + html.escape(msg) + '</div></div></div>'
            + '</body></html>'
        )


