from __future__ import annotations

import argparse
import json
import tempfile
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from iotmd.ai import answer_query
from iotmd.config import AiConfig, Inventory, load_inventory
from iotmd.generator import build_documents, write_documents


@dataclass
class WebState:
    ai: AiConfig = field(
        default_factory=lambda: AiConfig(
            enabled=True,
            api_base="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            model="qwen-turbo",
            api_key=None,
        )
    )
    inventory: Inventory | None = None
    snapshots: list = field(default_factory=list)
    last_output_dir: Path | None = None


def run_web(args: argparse.Namespace) -> None:
    state = WebState()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, content: str, content_type: str = "text/html; charset=utf-8") -> None:
            data = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(_index_html())
                return
            if parsed.path == "/api/status":
                with lock:
                    self._send_json(
                        {
                            "loaded": state.inventory is not None,
                            "snapshotCount": len(state.snapshots),
                            "downloadReady": state.last_output_dir is not None,
                        }
                    )
                return
            if parsed.path == "/download/summary.md":
                with lock:
                    if not state.last_output_dir:
                        self.send_error(HTTPStatus.NOT_FOUND, "暂无可下载文件")
                        return
                    file_path = state.last_output_dir / "summary.md"
                if not file_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "文件不存在")
                    return
                content = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="summary.md"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json({"error": "JSON 格式错误"}, status=400)
                return

            if parsed.path == "/api/load_inventory":
                yaml_text = str(payload.get("inventoryYaml", "")).strip()
                timeout = int(payload.get("timeout", args.timeout))
                if not yaml_text:
                    self._send_json({"error": "inventoryYaml 不能为空"}, status=400)
                    return
                try:
                    with tempfile.NamedTemporaryFile("w", suffix=".yaml", encoding="utf-8", delete=False) as tmp:
                        tmp.write(yaml_text)
                        tmp_path = Path(tmp.name)
                    inventory = load_inventory(tmp_path)
                    snapshots = _collect_snapshots_web(inventory, timeout)
                except Exception as exc:  # noqa: BLE001
                    self._send_json({"error": f"加载失败: {exc}"}, status=400)
                    return
                finally:
                    if "tmp_path" in locals() and tmp_path.exists():
                        tmp_path.unlink(missing_ok=True)

                with lock:
                    state.inventory = inventory
                    state.ai = inventory.ai
                    state.snapshots = snapshots
                self._send_json(
                    {
                        "message": f"设备清单已加载，采集成功 {len(snapshots)} 台。你可以直接在对话里输入“生成文档”。"
                    }
                )
                return

            if parsed.path == "/api/chat":
                message = str(payload.get("message", "")).strip()
                if not message:
                    self._send_json({"error": "message 不能为空"}, status=400)
                    return

                lowered = message.lower()
                if message in {"生成文档", "生成交换机文档", "发送文档"}:
                    with lock:
                        if not state.inventory:
                            self._send_json(
                                {
                                    "reply": "我还没有设备数据。请先上传 inventory.yaml（左上角“上传设备清单”），我会自动采集后再生成文档。"
                                }
                            )
                            return
                        if not state.snapshots:
                            self._send_json(
                                {
                                    "reply": "当前没有可用设备快照（可能全部采集失败），请检查网络/账号后重新上传清单。"
                                }
                            )
                            return
                        out_dir = Path(args.output)
                        bundle = build_documents(state.inventory, state.snapshots)
                        write_documents(bundle, out_dir)
                        state.last_output_dir = out_dir
                    self._send_json(
                        {
                            "reply": "文档已生成完成，我已把文件准备好了。",
                            "downloadUrl": "/download/summary.md",
                        }
                    )
                    return

                if lowered in {"help", "帮助", "指令"}:
                    self._send_json(
                        {
                            "reply": (
                                "可用指令：\n"
                                "1) 生成文档 / 发送文档\n"
                                "2) 帮助\n"
                                "提示：先上传 inventory.yaml，系统会自动采集。"
                            )
                        }
                    )
                    return

                with lock:
                    response = answer_query(message, state.snapshots, state.ai)
                self._send_json({"reply": response})
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web UI 启动成功: http://{args.host}:{args.port}")
    server.serve_forever()


def _collect_snapshots_web(inventory: Inventory, timeout: int) -> list:
    from paramiko.ssh_exception import AuthenticationException

    from iotmd.collectors.huawei import collect_huawei
    from iotmd.collectors.ruijie import collect_ruijie

    collectors = {"huawei": collect_huawei, "ruijie": collect_ruijie}
    snapshots: list = []
    for device in inventory.devices:
        collector = collectors.get(device.vendor)
        if not collector:
            continue
        try:
            snapshots.append(
                collector(
                    name=device.name,
                    host=device.host,
                    port=device.port,
                    username=device.username,
                    password=device.password,
                    timeout=timeout,
                )
            )
        except AuthenticationException:
            continue
        except Exception:
            continue
    return snapshots


def _index_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>IotMd 对话助手</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --panel-2: #1f2937;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --brand: #22c55e;
      --user: #2563eb;
      --ai: #374151;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, Arial, sans-serif;
      background: radial-gradient(circle at top left, #1f2937 0%, var(--bg) 45%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      padding: 24px;
    }
    .app {
      width: min(980px, 100%);
      background: rgba(17, 24, 39, 0.95);
      border: 1px solid #334155;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 25px 60px rgba(0,0,0,0.35);
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-height: 78vh;
    }
    .header {
      padding: 16px 18px;
      border-bottom: 1px solid #334155;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .title { font-weight: 700; }
    .muted { color: var(--muted); font-size: 13px; }
    .upload { display: flex; align-items: center; gap: 8px; }
    .upload textarea { display: none; }
    .btn {
      border: none;
      padding: 9px 14px;
      border-radius: 10px;
      cursor: pointer;
      color: white;
      background: var(--panel-2);
    }
    .btn.brand { background: var(--brand); color: #052e16; font-weight: 700; }
    .chat {
      padding: 18px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      background: linear-gradient(180deg, rgba(17,24,39,.4), rgba(15,23,42,.4));
    }
    .bubble {
      max-width: 80%;
      padding: 12px 14px;
      border-radius: 14px;
      white-space: pre-wrap;
      line-height: 1.45;
      border: 1px solid #475569;
    }
    .user { align-self: flex-end; background: var(--user); border-color: #60a5fa; }
    .ai { align-self: flex-start; background: var(--ai); }
    .toolbar {
      border-top: 1px solid #334155;
      padding: 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      background: var(--panel);
    }
    input[type=text] {
      width: 100%;
      border: 1px solid #475569;
      border-radius: 10px;
      padding: 12px;
      background: #0b1220;
      color: var(--text);
      outline: none;
    }
    a.download {
      color: #86efac;
      text-decoration: none;
      font-weight: 600;
      display: inline-block;
      margin-top: 6px;
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <div>
        <div class="title">IotMd 智能运维对话助手</div>
        <div class="muted">先上传 inventory.yaml 自动采集，然后直接在对话输入“生成文档”即可发送文档。</div>
      </div>
      <div class="upload">
        <input id="file" type="file" accept=".yaml,.yml,text/plain" />
        <button class="btn brand" onclick="uploadInventory()">上传设备清单</button>
      </div>
    </div>

    <div id="chat" class="chat"></div>

    <div class="toolbar">
      <input id="msg" type="text" placeholder="输入消息（例如：你好 / 生成文档 / 帮助）" />
      <button class="btn" onclick="sendMsg()">发送</button>
    </div>
  </div>

<script>
function addBubble(text, role='ai', downloadUrl='') {
  const chat = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = `bubble ${role}`;
  el.textContent = text;
  if (downloadUrl) {
    const link = document.createElement('a');
    link.className = 'download';
    link.href = downloadUrl;
    link.textContent = '⬇ 下载 summary.md';
    el.appendChild(document.createElement('br'));
    el.appendChild(link);
  }
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
}

async function uploadInventory() {
  const f = document.getElementById('file').files[0];
  if (!f) {
    addBubble('请先选择一个 inventory.yaml 文件。', 'ai');
    return;
  }
  const text = await f.text();
  addBubble(`已上传清单文件：${f.name}，正在采集设备...`, 'user');
  const resp = await fetch('/api/load_inventory', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({inventoryYaml: text})
  });
  const data = await resp.json();
  addBubble(data.message || data.error || '处理完成。', 'ai');
}

async function sendMsg() {
  const input = document.getElementById('msg');
  const message = input.value.trim();
  if (!message) return;
  addBubble(message, 'user');
  input.value = '';
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message})
  });
  const data = await resp.json();
  addBubble(data.reply || data.error || '无响应', 'ai', data.downloadUrl || '');
}

document.getElementById('msg').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMsg();
});

addBubble('你好，我是 IotMd 助手。先上传设备清单，然后你可以直接说“生成文档”。', 'ai');
</script>
</body>
</html>
"""
