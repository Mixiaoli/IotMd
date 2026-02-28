from __future__ import annotations

import argparse
import os
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from iotmd.ai import answer_query_live, resolve_api_key
from iotmd.config import AiConfig, DeviceConfig, Inventory, load_inventory
from iotmd.discovery import scan_subnet
from iotmd.generator import build_documents, write_documents


@dataclass
class Defaults:
    vendor: str = "huawei"
    port: int = 22
    username: str = "admin"
    password: str = ""


@dataclass
class ConversationForm:
    active: bool = False
    site: str = "HQ"
    owner: str = "NetOps"
    phone: str = ""
    email: str = ""
    mode: str = "manual"  # manual | scan
    device_count: int = 1
    devices: list[DeviceConfig] = field(default_factory=list)
    current_device: dict[str, str] = field(default_factory=dict)
    step: str = "site"
    scan_vendor: str = "huawei"
    scan_cidr: str = "10.133.12.0/24"
    scan_port: int = 22
    use_default_credentials: bool = True
    scan_username: str = "admin"
    scan_password: str = ""


@dataclass
class WebState:
    ai: AiConfig
    defaults: Defaults
    inventory: Inventory | None = None
    snapshots: list = field(default_factory=list)
    last_output_dir: Path | None = None
    form: ConversationForm = field(default_factory=ConversationForm)


def run_web(args: argparse.Namespace) -> None:
    state = _build_initial_state(args)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            import json

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

            if parsed.path.startswith("/download/"):
                with lock:
                    if not state.last_output_dir:
                        self.send_error(HTTPStatus.NOT_FOUND, "暂无可下载文件")
                        return
                    file_path = state.last_output_dir / parsed.path.replace("/download/", "")
                if not file_path.exists() or not file_path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "文件不存在")
                    return
                content = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

        def do_POST(self) -> None:  # noqa: N802
            import json

            parsed = urlparse(self.path)
            if parsed.path != "/api/chat":
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json({"error": "JSON 格式错误"}, status=400)
                return

            # allow empty input to represent default during form flow
            message_raw = payload.get("message", "")
            message = str(message_raw) if message_raw is not None else ""

            with lock:
                reply, download_links = _handle_chat_message(state, message, args)
            body: dict[str, Any] = {"reply": reply}
            if download_links:
                body["downloadLinks"] = download_links
            self._send_json(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web UI 启动成功: http://{args.host}:{args.port}")
    server.serve_forever()


def _build_initial_state(args: argparse.Namespace) -> WebState:
    defaults = Defaults()
    ai = AiConfig(
        enabled=True,
        api_base="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        model="qwen-turbo",
        api_key=resolve_api_key(None),
    )

    try:
        inv = load_inventory(Path(args.inventory))
        ai = AiConfig(
            enabled=True,
            api_base=inv.ai.api_base,
            model=inv.ai.model,
            api_key=resolve_api_key(inv.ai.api_key),
        )
        if inv.devices:
            first = inv.devices[0]
            defaults = Defaults(
                vendor=first.vendor,
                port=first.port,
                username=first.username,
                password=first.password,
            )
    except Exception:
        pass

    # env key overrides
    env_key = os.environ.get("DASHSCOPE_API_KEY")
    if env_key:
        ai = AiConfig(enabled=True, api_base=ai.api_base, model=ai.model, api_key=env_key)

    return WebState(ai=ai, defaults=defaults)


def _handle_chat_message(state: WebState, message: str, args: argparse.Namespace) -> tuple[str, list[dict[str, str]]]:
    if message == "__DEFAULT__":
        message = ""
    lowered = message.strip().lower()

    if lowered in {"help", "帮助", "指令"}:
        return (
            "可用指令：\n"
            "1) 生成文档（进入问答采集流程）\n"
            "2) 设置key sk-xxx（覆盖配置文件中的 key）\n"
            "3) 取消（中断当前采集问答）\n"
            "说明：直接回车（空白）可以采用默认值。",
            [],
        )

    if lowered.startswith("设置key ") or lowered.startswith("set key "):
        key = message.split(" ", 1)[1].strip()
        if not key:
            return "请在“设置key ”后面输入你的 API Key。", []
        state.ai = AiConfig(enabled=True, api_base=state.ai.api_base, model=state.ai.model, api_key=key)
        return "API Key 已设置成功。", []

    if lowered in {"取消", "cancel"} and state.form.active:
        state.form = ConversationForm()
        return "已取消本次信息采集。你可以随时再输入“生成文档”重新开始。", []

    if state.form.active:
        return _consume_form_answer(state, message, args)

    if lowered in {"生成文档", "生成交换机文档", "发送文档"}:
        state.form = ConversationForm(active=True, step="site")
        state.form.scan_vendor = state.defaults.vendor
        state.form.scan_port = state.defaults.port
        state.form.scan_username = state.defaults.username
        state.form.scan_password = state.defaults.password
        return "好的，开始收集文档信息。第 1 步：请输入站点名称（默认：HQ）。", []

    if not resolve_api_key(state.ai.api_key):
        return "当前未配置 API Key（且配置文件/环境变量中未读取到）。请发送：设置key 你的Key。", []

    try:
        response = answer_query_live(message.strip() or "你好", state.snapshots, state.ai)
    except RuntimeError as exc:
        return (f"真实 AI 调用失败：{exc}", [])
    return response, []


def _consume_form_answer(state: WebState, message: str, args: argparse.Namespace) -> tuple[str, list[dict[str, str]]]:
    form = state.form
    text = message.strip()

    if form.step == "site":
        form.site = text or "HQ"
        form.step = "owner"
        return "第 2 步：请输入负责人（默认：NetOps）。", []

    if form.step == "owner":
        form.owner = text or "NetOps"
        form.step = "phone"
        return "第 3 步：请输入联系电话（可留空，回车表示空）。", []

    if form.step == "phone":
        form.phone = text
        form.step = "email"
        return "第 4 步：请输入联系邮箱（可留空，回车表示空）。", []

    if form.step == "email":
        form.email = text
        form.step = "mode"
        return "第 5 步：采集方式？输入 manual（逐台）或 scan（扫描网段），默认 manual。", []

    if form.step == "mode":
        mode = (text or "manual").lower()
        if mode not in {"manual", "scan"}:
            return "采集方式仅支持 manual 或 scan。", []
        form.mode = mode
        if mode == "scan":
            form.step = "scan_cidr"
            return "请输入扫描网段 CIDR（默认：10.133.12.0/24）。", []
        form.step = "device_count"
        return "第 6 步：请输入设备数量（默认：1）。", []

    if form.step == "scan_cidr":
        form.scan_cidr = text or "10.133.12.0/24"
        form.step = "scan_vendor"
        return f"请输入扫描设备厂商（huawei/ruijie，默认：{state.defaults.vendor}）。", []

    if form.step == "scan_vendor":
        vendor = (text or state.defaults.vendor).lower()
        if vendor not in {"huawei", "ruijie"}:
            return "厂商仅支持 huawei 或 ruijie。", []
        form.scan_vendor = vendor
        form.step = "scan_port"
        return f"请输入 SSH 端口（默认：{state.defaults.port}）。", []

    if form.step == "scan_port":
        try:
            form.scan_port = int(text or str(state.defaults.port))
        except ValueError:
            return "端口格式错误，请输入数字。", []
        form.step = "scan_use_default_creds"
        return (
            f"默认账号密码来自配置文件：{state.defaults.username}/******。是否直接使用默认账号密码？(y/n，默认 y)",
            [],
        )

    if form.step == "scan_use_default_creds":
        use_default = (text or "y").lower() != "n"
        form.use_default_credentials = use_default
        if use_default:
            form.scan_username = state.defaults.username
            form.scan_password = state.defaults.password
            return _finalize_scan_mode(state, args)
        form.step = "scan_username"
        return f"请输入扫描登录用户名（默认：{state.defaults.username}）。", []

    if form.step == "scan_username":
        form.scan_username = text or state.defaults.username
        form.step = "scan_password"
        return "请输入扫描登录密码（回车表示使用配置文件默认密码）。", []

    if form.step == "scan_password":
        form.scan_password = text or state.defaults.password
        return _finalize_scan_mode(state, args)

    if form.step == "device_count":
        try:
            form.device_count = max(1, int(text or "1"))
        except ValueError:
            return "设备数量格式不正确，请输入数字。", []
        form.current_device = {}
        form.step = "device_name"
        return "设备 1：请输入设备名称（默认：device-1）。", []

    idx = len(form.devices) + 1
    if form.step == "device_name":
        form.current_device["name"] = text or f"device-{idx}"
        form.step = "device_vendor"
        return f"设备 {idx}：请输入厂商（huawei/ruijie，默认：{state.defaults.vendor}）。", []

    if form.step == "device_vendor":
        vendor = (text or state.defaults.vendor).lower()
        if vendor not in {"huawei", "ruijie"}:
            return "厂商仅支持 huawei 或 ruijie，请重新输入。", []
        form.current_device["vendor"] = vendor
        form.step = "device_host"
        return f"设备 {idx}：请输入管理 IP。", []

    if form.step == "device_host":
        if not text:
            return "管理 IP 不能为空。", []
        form.current_device["host"] = text
        form.step = "device_port"
        return f"设备 {idx}：请输入 SSH 端口（默认：{state.defaults.port}）。", []

    if form.step == "device_port":
        try:
            port = int(text or str(state.defaults.port))
            if port <= 0:
                raise ValueError
        except ValueError:
            return "SSH 端口格式错误，请输入正整数。", []
        form.current_device["port"] = str(port)
        form.step = "device_username"
        return f"设备 {idx}：请输入登录用户名（默认：{state.defaults.username}）。", []

    if form.step == "device_username":
        form.current_device["username"] = text or state.defaults.username
        form.step = "device_password"
        return f"设备 {idx}：请输入登录密码（回车表示使用配置文件默认密码）。", []

    if form.step == "device_password":
        form.current_device["password"] = text or state.defaults.password
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
            form.current_device = {}
            form.step = "device_name"
            next_idx = len(form.devices) + 1
            return f"设备 {next_idx}：请输入设备名称（默认：device-{next_idx}）。", []

        inventory = Inventory(
            site=form.site,
            contacts={"owner": form.owner, "phone": form.phone, "email": form.email},
            ai=state.ai,
            devices=form.devices,
        )
        return _collect_and_generate(state, inventory, args)

    return "流程状态异常，请输入“取消”后重新开始。", []


def _finalize_scan_mode(state: WebState, args: argparse.Namespace) -> tuple[str, list[dict[str, str]]]:
    form = state.form
    hosts = scan_subnet(form.scan_cidr, ssh_port=form.scan_port, timeout=0.7)
    devices: list[DeviceConfig] = []
    counter = 1
    for host in hosts:
        if not host.ssh_open:
            continue
        devices.append(
            DeviceConfig(
                name=f"{form.scan_vendor}-auto-{counter}",
                vendor=form.scan_vendor,
                host=host.host,
                port=form.scan_port,
                username=form.scan_username,
                password=form.scan_password,
            )
        )
        counter += 1

    inventory = Inventory(
        site=form.site,
        contacts={"owner": form.owner, "phone": form.phone, "email": form.email},
        ai=state.ai,
        devices=devices,
        subnet_cidr=form.scan_cidr,
        subnet_hosts=hosts,
    )
    return _collect_and_generate(state, inventory, args)


def _collect_and_generate(state: WebState, inventory: Inventory, args: argparse.Namespace) -> tuple[str, list[dict[str, str]]]:
    snapshots = _collect_snapshots_web(inventory, args.timeout)
    state.inventory = inventory
    state.snapshots = snapshots
    state.form = ConversationForm()

    if not snapshots:
        return "信息已收集完成，但设备采集全部失败，暂无法生成文档。请检查网络和账号后重试。", []

    out_dir = Path(args.output)
    bundle = build_documents(inventory, snapshots)
    write_documents(bundle, out_dir)
    state.last_output_dir = out_dir

    links = [{"label": "下载 summary.md", "url": "/download/summary.md"}]
    links.extend(
        {"label": f"下载 {filename}", "url": f"/download/{filename}"}
        for filename in sorted(bundle.device_documents.keys())
    )
    return f"已完成采集并生成文档（成功 {len(snapshots)} 台）。", links


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
    :root { --bg:#0f172a; --panel:#111827; --text:#e5e7eb; --muted:#9ca3af; --user:#2563eb; --ai:#374151; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Inter,Arial,sans-serif; background:radial-gradient(circle at top left,#1f2937 0%,var(--bg) 45%); color:var(--text); min-height:100vh; display:flex; justify-content:center; padding:24px; }
    .app { width:min(980px,100%); background:rgba(17,24,39,.95); border:1px solid #334155; border-radius:16px; overflow:hidden; box-shadow:0 25px 60px rgba(0,0,0,.35); display:grid; grid-template-rows:auto 1fr auto; min-height:78vh; }
    .header { padding:16px 18px; border-bottom:1px solid #334155; }
    .title { font-weight:700; }
    .muted { color:var(--muted); font-size:13px; margin-top:6px; }
    .chat { padding:18px; overflow-y:auto; display:flex; flex-direction:column; gap:10px; background:linear-gradient(180deg, rgba(17,24,39,.4), rgba(15,23,42,.4)); scrollbar-width: thin; }
    .chat::-webkit-scrollbar { width: 10px; }
    .chat::-webkit-scrollbar-thumb { background: #475569; border-radius: 8px; }
    .bubble { max-width:80%; padding:12px 14px; border-radius:14px; white-space:pre-wrap; line-height:1.45; border:1px solid #475569; }
    .user { align-self:flex-end; background:var(--user); border-color:#60a5fa; }
    .ai { align-self:flex-start; background:var(--ai); }
    .toolbar { border-top:1px solid #334155; padding:12px; display:grid; grid-template-columns:1fr auto; gap:10px; background:var(--panel); }
    input[type=text] { width:100%; border:1px solid #475569; border-radius:10px; padding:12px; background:#0b1220; color:var(--text); outline:none; }
    button { border:none; padding:9px 14px; border-radius:10px; cursor:pointer; color:white; background:#1f2937; }
    a.download { color:#86efac; text-decoration:none; font-weight:600; display:inline-block; margin-top:6px; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <div class="title">IotMd 智能运维对话助手</div>
      <div class="muted">支持扫描网段自动发现交换机。直接回车可采用默认值。生成后会输出 summary.md 和每台设备IP对应的 md 文档。</div>
    </div>
    <div id="chat" class="chat"></div>
    <div class="toolbar">
      <input id="msg" type="text" placeholder="输入消息（例如：生成文档 / 设置key sk-xxx / 帮助；可直接回车用默认值）" />
      <button onclick="sendMsg()">发送</button>
    </div>
  </div>
<script>
function scrollBottom(){ const c=document.getElementById('chat'); c.scrollTo({top:c.scrollHeight, behavior:'smooth'}); }
function addBubble(text, role='ai', links=[]) {
  const chat = document.getElementById('chat');
  const el = document.createElement('div');
  el.className = `bubble ${role}`;
  el.textContent = text;
  for (const item of links || []) {
    const a = document.createElement('a');
    a.className = 'download';
    a.href = item.url;
    a.textContent = `⬇ ${item.label}`;
    el.appendChild(document.createElement('br'));
    el.appendChild(a);
  }
  chat.appendChild(el);
  scrollBottom();
}

async function sendMsg(forceDefault=false) {
  const input = document.getElementById('msg');
  const raw = input.value;
  const message = forceDefault ? '__DEFAULT__' : raw;
  if (!forceDefault && !raw.trim()) return;
  if (!forceDefault) addBubble(raw, 'user');
  else addBubble('（使用默认值）', 'user');
  input.value = '';
  const resp = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message})
  });
  const data = await resp.json();
  addBubble(data.reply || data.error || '无响应', 'ai', data.downloadLinks || []);
}

document.getElementById('msg').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const raw = document.getElementById('msg').value;
    if (!raw.trim()) sendMsg(true);
    else sendMsg(false);
  }
});

addBubble('你好，我是 IotMd 助手。输入“生成文档”开始问答；也可以先“设置key 你的Key”启用真实 AI。', 'ai');
</script>
</body>
</html>
"""
