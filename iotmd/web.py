from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from iotmd.ai import answer_query
from iotmd.config import AiConfig, DeviceConfig, Inventory
from iotmd.generator import build_documents, write_documents


@dataclass
class ConversationForm:
    active: bool = False
    site: str = "HQ"
    owner: str = "NetOps"
    phone: str = ""
    email: str = ""
    device_count: int = 1
    devices: list[DeviceConfig] = field(default_factory=list)
    current_device: dict[str, str] = field(default_factory=dict)
    step: str = "site"


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
    form: ConversationForm = field(default_factory=ConversationForm)


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

            if parsed.path != "/api/chat":
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            message = str(payload.get("message", "")).strip()
            if not message:
                self._send_json({"error": "message 不能为空"}, status=400)
                return

            with lock:
                reply, download_url = _handle_chat_message(state, message, args)
            body = {"reply": reply}
            if download_url:
                body["downloadUrl"] = download_url
            self._send_json(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web UI 启动成功: http://{args.host}:{args.port}")
    server.serve_forever()


def _handle_chat_message(state: WebState, message: str, args: argparse.Namespace) -> tuple[str, str | None]:
    lowered = message.lower()
    if lowered in {"help", "帮助", "指令"}:
        return (
            "可用指令：\n"
            "1) 生成文档（进入问答采集流程）\n"
            "2) 取消（中断当前采集问答）\n"
            "3) 帮助\n"
            "你不需要上传 inventory 文件，我会在聊天里逐项问你。\n"
            "未生成文档前，你也可以直接进行普通聊天。",
            None,
        )

    if lowered in {"取消", "cancel"} and state.form.active:
        state.form = ConversationForm()
        return "已取消本次信息采集。你可以随时再输入“生成文档”重新开始。", None

    if state.form.active:
        return _consume_form_answer(state, message, args)

    if message in {"生成文档", "生成交换机文档", "发送文档"}:
        state.form = ConversationForm(active=True, step="site")
        return (
            "好的，我们通过问答来收集信息。\n"
            "第 1 步：请输入站点名称（默认：HQ）。",
            None,
        )

    response = answer_query(message, state.snapshots, state.ai)
    return response, None


def _consume_form_answer(state: WebState, message: str, args: argparse.Namespace) -> tuple[str, str | None]:
    form = state.form
    text = message.strip()

    if form.step == "site":
        form.site = text or "HQ"
        form.step = "owner"
        return "第 2 步：请输入负责人（默认：NetOps）。", None

    if form.step == "owner":
        form.owner = text or "NetOps"
        form.step = "phone"
        return "第 3 步：请输入联系电话（可留空）。", None

    if form.step == "phone":
        form.phone = text
        form.step = "email"
        return "第 4 步：请输入联系邮箱（可留空）。", None

    if form.step == "email":
        form.email = text
        form.step = "device_count"
        return "第 5 步：请输入设备数量（默认：1）。", None

    if form.step == "device_count":
        try:
            form.device_count = max(1, int(text or "1"))
        except ValueError:
            return "设备数量格式不正确，请输入数字，例如 1 或 3。", None
        form.current_device = {}
        form.step = "device_name"
        return "设备 1：请输入设备名称（默认：device-1）。", None

    device_index = len(form.devices) + 1

    if form.step == "device_name":
        form.current_device["name"] = text or f"device-{device_index}"
        form.step = "device_vendor"
        return f"设备 {device_index}：请输入厂商（huawei/ruijie，默认：huawei）。", None

    if form.step == "device_vendor":
        vendor = (text or "huawei").lower()
        if vendor not in {"huawei", "ruijie"}:
            return "厂商仅支持 huawei 或 ruijie，请重新输入。", None
        form.current_device["vendor"] = vendor
        form.step = "device_host"
        return f"设备 {device_index}：请输入管理 IP（例如 10.132.12.2）。", None

    if form.step == "device_host":
        if not text:
            return "管理 IP 不能为空，请重新输入。", None
        form.current_device["host"] = text
        form.step = "device_port"
        return f"设备 {device_index}：请输入 SSH 端口（默认：22）。", None

    if form.step == "device_port":
        try:
            port = int(text or "22")
            if port <= 0:
                raise ValueError
        except ValueError:
            return "SSH 端口格式错误，请输入正整数，例如 22。", None
        form.current_device["port"] = str(port)
        form.step = "device_username"
        return f"设备 {device_index}：请输入登录用户名（默认：admin）。", None

    if form.step == "device_username":
        form.current_device["username"] = text or "admin"
        form.step = "device_password"
        return f"设备 {device_index}：请输入登录密码。", None

    if form.step == "device_password":
        if not text:
            return "密码不能为空，请重新输入。", None
        form.current_device["password"] = text
        form.devices.append(
            DeviceConfig(
                name=form.current_device["name"],
                vendor=form.current_device["vendor"],
                host=form.current_device["host"],
                port=int(form.current_device["port"]),
                username=form.current_device["username"],
                password=form.current_device["password"],
            )
        )

        if len(form.devices) < form.device_count:
            next_index = len(form.devices) + 1
            form.current_device = {}
            form.step = "device_name"
            return f"设备 {next_index}：请输入设备名称（默认：device-{next_index}）。", None

        inventory = Inventory(
            site=form.site,
            contacts={"owner": form.owner, "phone": form.phone, "email": form.email},
            ai=state.ai,
            devices=form.devices,
        )
        snapshots = _collect_snapshots_web(inventory, args.timeout)
        state.inventory = inventory
        state.snapshots = snapshots

        if not snapshots:
            state.form = ConversationForm()
            return "信息已收集完成，但设备采集全部失败，暂无法生成文档。请检查网络和账号后重试。", None

        out_dir = Path(args.output)
        bundle = build_documents(inventory, snapshots)
        write_documents(bundle, out_dir)
        state.last_output_dir = out_dir
        state.form = ConversationForm()
        return (
            f"已完成采集并生成文档（成功 {len(snapshots)} 台）。点击下方链接下载。",
            "/download/summary.md",
        )

    return "流程状态异常，请输入“取消”后重新开始。", None


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
      --text: #e5e7eb;
      --muted: #9ca3af;
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
    }
    .title { font-weight: 700; }
    .muted { color: var(--muted); font-size: 13px; margin-top: 6px; }
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
    button {
      border: none;
      padding: 9px 14px;
      border-radius: 10px;
      cursor: pointer;
      color: white;
      background: #1f2937;
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
      <div class="title">IotMd 智能运维对话助手</div>
      <div class="muted">你可以直接普通聊天；如果输入“生成文档”，我会通过问答收集信息并自动生成文档发送给你。</div>
    </div>

    <div id="chat" class="chat"></div>

    <div class="toolbar">
      <input id="msg" type="text" placeholder="输入消息（例如：你好 / 网络趋势 / 生成文档 / 帮助 / 取消）" />
      <button onclick="sendMsg()">发送</button>
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

addBubble('你好，我是 IotMd 助手。你可以先正常聊天；需要出文档时再输入“生成文档”。', 'ai');
</script>
</body>
</html>
"""
