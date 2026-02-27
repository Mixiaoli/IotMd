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

            if parsed.path == "/api/chat":
                message = str(payload.get("message", "")).strip()
                if not message:
                    self._send_json({"error": "message 不能为空"}, status=400)
                    return
                with lock:
                    response = answer_query(message, state.snapshots, state.ai)
                self._send_json({"reply": response})
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
                self._send_json({"message": f"已加载设备，采集成功 {len(snapshots)} 台"})
                return

            if parsed.path == "/api/generate":
                with lock:
                    if not state.inventory:
                        self._send_json({"error": "请先加载设备清单"}, status=400)
                        return
                    if not state.snapshots:
                        self._send_json({"error": "尚无可用快照，无法生成文档"}, status=400)
                        return
                    out_dir = Path(args.output)
                    bundle = build_documents(state.inventory, state.snapshots)
                    write_documents(bundle, out_dir)
                    state.last_output_dir = out_dir
                self._send_json(
                    {
                        "message": "文档已生成",
                        "downloadUrl": "/download/summary.md",
                    }
                )
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
  <title>IotMd Web 助手</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; max-width: 1000px; }
    .row { display: flex; gap: 16px; }
    .col { flex: 1; }
    textarea, input, button { width: 100%; margin-top: 8px; box-sizing: border-box; }
    textarea { min-height: 140px; }
    #chat { border: 1px solid #ddd; padding: 12px; min-height: 260px; white-space: pre-wrap; background: #fafafa; }
    .muted { color: #666; font-size: 13px; }
  </style>
</head>
<body>
  <h2>IotMd Web 对话与文档助手</h2>
  <p class="muted">流程：粘贴 inventory.yaml → 加载采集 → 对话提问 → 生成文档并下载 summary.md</p>
  <div class="row">
    <div class="col">
      <h3>1) 设备清单</h3>
      <textarea id="inv" placeholder="粘贴 inventory.yaml"></textarea>
      <button onclick="loadInventory()">加载并采集</button>
      <p id="loadMsg" class="muted"></p>
      <h3>2) 生成文档</h3>
      <button onclick="generateDocs()">生成文档</button>
      <a id="download" href="#" style="display:none;">下载 summary.md</a>
    </div>
    <div class="col">
      <h3>3) 对话</h3>
      <div id="chat"></div>
      <input id="msg" placeholder="请输入问题" />
      <button onclick="sendMsg()">发送</button>
    </div>
  </div>

<script>
function append(role, text) {
  const box = document.getElementById('chat');
  box.textContent += `${role}: ${text}\n\n`;
  box.scrollTop = box.scrollHeight;
}
async function loadInventory() {
  const inventoryYaml = document.getElementById('inv').value;
  const resp = await fetch('/api/load_inventory', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({inventoryYaml})
  });
  const data = await resp.json();
  document.getElementById('loadMsg').textContent = data.message || data.error;
}
async function sendMsg() {
  const message = document.getElementById('msg').value;
  if (!message) return;
  append('你', message);
  document.getElementById('msg').value = '';
  const resp = await fetch('/api/chat', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message})
  });
  const data = await resp.json();
  append('AI', data.reply || data.error || '无响应');
}
async function generateDocs() {
  const resp = await fetch('/api/generate', {method: 'POST'});
  const data = await resp.json();
  if (data.downloadUrl) {
    const a = document.getElementById('download');
    a.href = data.downloadUrl;
    a.style.display = 'inline-block';
    a.textContent = '下载 summary.md';
  }
  document.getElementById('loadMsg').textContent = data.message || data.error;
}
</script>
</body>
</html>
"""
