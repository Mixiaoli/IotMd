from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple
import argparse
import ipaddress
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from iotmd.ai import answer_query_live, is_requests_available, resolve_api_key
from iotmd.config import AiConfig, DeviceConfig, Inventory, load_inventory
from iotmd.generator import build_documents, write_documents


# ----------------------------
# data models
# ----------------------------
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

    # scan fields
    scan_vendor: str = "huawei"
    scan_cidr: str = "10.133.12.0/24"
    scan_port: int = 22
    use_default_credentials: bool = True
    scan_username: str = "admin"
    scan_password: str = ""


@dataclass
class JobState:
    job_id: str
    status: str = "running"  # running | done | failed
    phase: str = "init"      # init | scanning | collecting | generating | done | failed
    message: str = ""

    # scan stats (live)
    scan_target_total: int = 0        # CIDR里总IP数量（可选，用于百分比/参考）
    scanned_ips: int = 0              # 已扫描IP数
    found_open: int = 0               # 端口可达数（发现）
    ssh_open: int = 0                 # SSH可连接数（这里与 found_open 一致：端口可达即认为可连接）

    # collect stats (live)
    total_devices: int = 0
    collected_ok: int = 0
    collected_failed: int = 0

    download_links: list[dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


@dataclass
class WebState:
    ai: AiConfig
    defaults: Defaults
    key_source: str = "none"
    startup_notice: str = ""
    inventory: Optional[Inventory] = None
    snapshots: list = field(default_factory=list)
    last_output_dir: Optional[Path] = None
    form: ConversationForm = field(default_factory=ConversationForm)
    jobs: dict[str, JobState] = field(default_factory=dict)


# ----------------------------
# main web server
# ----------------------------
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

            # job status for polling
            if parsed.path.startswith("/api/job/"):
                job_id = parsed.path.replace("/api/job/", "", 1).strip()
                with lock:
                    job = state.jobs.get(job_id)
                    if not job:
                        self._send_json({"error": "Job not found"}, status=404)
                        return
                    payload = {
                        "jobId": job.job_id,
                        "status": job.status,
                        "phase": job.phase,
                        "message": job.message,
                        "scanTargetTotal": job.scan_target_total,
                        "scannedIps": job.scanned_ips,
                        "foundOpen": job.found_open,
                        "sshOpen": job.ssh_open,
                        "totalDevices": job.total_devices,
                        "collectedOk": job.collected_ok,
                        "collectedFailed": job.collected_failed,
                        "downloadLinks": job.download_links,
                        "finished": job.finished_at is not None,
                    }
                self._send_json(payload)
                return

            # download generated md files
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

            message_raw = payload.get("message", "")
            message = str(message_raw) if message_raw is not None else ""

            with lock:
                reply, download_links, job_id = _handle_chat_message(state, message, args, lock)

            body: dict[str, Any] = {"reply": reply}
            if download_links:
                body["downloadLinks"] = download_links
            if job_id:
                body["jobId"] = job_id
            self._send_json(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Web UI 启动成功: http://{args.host}:{args.port}")
    server.serve_forever()


# ----------------------------
# state init
# ----------------------------
def _build_initial_state(args: argparse.Namespace) -> WebState:
    defaults = Defaults()
    ai = AiConfig(
        enabled=True,
        api_base="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        model="qwen-turbo",
        api_key=resolve_api_key(None),
    )

    key_source = "none"
    startup_notice = ""
    inventory_path = Path(args.inventory)

    try:
        inv = load_inventory(inventory_path)
        ai = AiConfig(
            enabled=True,
            api_base=inv.ai.api_base,
            model=inv.ai.model,
            api_key=resolve_api_key(inv.ai.api_key),
        )
        if ai.api_key:
            key_source = f"inventory({inventory_path})"
        if inv.devices:
            first = inv.devices[0]
            defaults = Defaults(
                vendor=first.vendor,
                port=first.port,
                username=first.username,
                password=first.password,
            )
    except Exception as exc:  # noqa: BLE001
        startup_notice = f"读取配置文件 {inventory_path} 失败：{exc}"

    env_key = os.environ.get("DASHSCOPE_API_KEY")
    if env_key:
        ai = AiConfig(enabled=True, api_base=ai.api_base, model=ai.model, api_key=env_key)
        key_source = "env(DASHSCOPE_API_KEY)"

    if not is_requests_available():
        missing_notice = "当前环境缺少 requests 依赖，真实 AI 无法调用。请先安装 requirements.txt。"
        startup_notice = f"{startup_notice}；{missing_notice}" if startup_notice else missing_notice

    return WebState(ai=ai, defaults=defaults, key_source=key_source, startup_notice=startup_notice)


# ----------------------------
# chat handler
# ----------------------------
def _handle_chat_message(
    state: WebState, message: str, args: argparse.Namespace, lock: threading.Lock
) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
    if message == "__DEFAULT__":
        message = ""
    lowered = message.strip().lower()

    if lowered in {"help", "帮助", "指令"}:
        return (
            "可用指令：\n"
            "1) 生成文档（进入问答采集流程）\n"
            "2) 设置key sk-xxx（覆盖配置文件中的 key）\n"
            "3) 取消（中断当前采集问答）\n"
            "说明：直接回车（空白）可以采用默认值。\n"
            f"当前 key 来源: {state.key_source if state.key_source != 'none' else '未配置'}。",
            [],
            None,
        )

    if lowered.startswith("设置key ") or lowered.startswith("set key "):
        key = message.split(" ", 1)[1].strip()
        if not key:
            return "请在“设置key ”后面输入你的 API Key。", [], None
        state.ai = AiConfig(enabled=True, api_base=state.ai.api_base, model=state.ai.model, api_key=key)
        state.key_source = "manual(chat)"
        return "API Key 已设置成功。", [], None

    if lowered in {"取消", "cancel"} and state.form.active:
        state.form = ConversationForm()
        return "已取消本次信息采集。你可以随时再输入“生成文档”重新开始。", [], None

    if state.form.active:
        return _consume_form_answer(state, message, args, lock)

    if lowered in {"生成文档", "生成交换机文档", "发送文档"}:
        state.form = ConversationForm(active=True, step="site")
        state.form.scan_vendor = state.defaults.vendor
        state.form.scan_port = state.defaults.port
        state.form.scan_username = state.defaults.username
        state.form.scan_password = state.defaults.password
        return "好的，开始收集文档信息。第 1 步：请输入站点名称（默认：HQ）。", [], None

    if state.startup_notice:
        notice = state.startup_notice
        state.startup_notice = ""
        return notice, [], None

    if not is_requests_available():
        return "当前环境缺少 requests 依赖，无法调用真实 AI。请先安装 requirements.txt。", [], None

    if not resolve_api_key(state.ai.api_key):
        return "当前未配置 API Key（未从 inventory.yaml / 环境变量读取到）。请发送：设置key 你的Key。", [], None

    try:
        response = answer_query_live(message.strip() or "你好", state.snapshots, state.ai)
    except RuntimeError as exc:
        return f"真实 AI 调用失败：{exc}", [], None

    return response, [], None


# ----------------------------
# form flow
# ----------------------------
def _consume_form_answer(
    state: WebState, message: str, args: argparse.Namespace, lock: threading.Lock
) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
    form = state.form
    text = message.strip()

    if form.step == "site":
        form.site = text or "HQ"
        form.step = "owner"
        return "第 2 步：请输入负责人（默认：NetOps）。", [], None

    if form.step == "owner":
        form.owner = text or "NetOps"
        form.step = "phone"
        return "第 3 步：请输入联系电话（可留空，回车表示空）。", [], None

    if form.step == "phone":
        form.phone = text
        form.step = "email"
        return "第 4 步：请输入联系邮箱（可留空，回车表示空）。", [], None

    if form.step == "email":
        form.email = text
        form.step = "mode"
        return "第 5 步：采集方式？输入 manual（逐台）或 scan（扫描网段），默认 manual。", [], None

    if form.step == "mode":
        mode = (text or "manual").lower()
        if mode not in {"manual", "scan"}:
            return "采集方式仅支持 manual 或 scan。", [], None
        form.mode = mode
        if mode == "scan":
            form.step = "scan_cidr"
            return "请输入扫描网段 CIDR（默认：10.133.12.0/24）。", [], None
        form.step = "device_count"
        return "第 6 步：请输入设备数量（默认：1）。", [], None

    if form.step == "scan_cidr":
        form.scan_cidr = text or "10.133.12.0/24"
        form.step = "scan_vendor"
        return f"请输入扫描设备厂商（huawei/ruijie，默认：{state.defaults.vendor}）。", [], None

    if form.step == "scan_vendor":
        vendor = (text or state.defaults.vendor).lower()
        if vendor not in {"huawei", "ruijie"}:
            return "厂商仅支持 huawei 或 ruijie。", [], None
        form.scan_vendor = vendor
        form.step = "scan_port"
        return f"请输入 SSH 端口（默认：{state.defaults.port}）。", [], None

    if form.step == "scan_port":
        try:
            form.scan_port = int(text or str(state.defaults.port))
        except ValueError:
            return "端口格式错误，请输入数字。", [], None
        form.step = "scan_use_default_creds"
        return (
            f"默认账号密码来自配置文件：{state.defaults.username}/******。是否直接使用默认账号密码？(y/n，默认 y)",
            [],
            None,
        )

    if form.step == "scan_use_default_creds":
        use_default = (text or "y").lower() != "n"
        form.use_default_credentials = use_default
        if use_default:
            form.scan_username = state.defaults.username
            form.scan_password = state.defaults.password
            return _start_job_scan_mode(state, args, lock)
        form.step = "scan_username"
        return f"请输入扫描登录用户名（默认：{state.defaults.username}）。", [], None

    if form.step == "scan_username":
        form.scan_username = text or state.defaults.username
        form.step = "scan_password"
        return "请输入扫描登录密码（回车表示使用配置文件默认密码）。", [], None

    if form.step == "scan_password":
        form.scan_password = text or state.defaults.password
        return _start_job_scan_mode(state, args, lock)

    # manual mode
    if form.step == "device_count":
        try:
            form.device_count = max(1, int(text or "1"))
        except ValueError:
            return "设备数量格式不正确，请输入数字。", [], None
        form.current_device = {}
        form.step = "device_name"
        return "设备 1：请输入设备名称（默认：device-1）。", [], None

    idx = len(form.devices) + 1
    if form.step == "device_name":
        form.current_device["name"] = text or f"device-{idx}"
        form.step = "device_vendor"
        return f"设备 {idx}：请输入厂商（huawei/ruijie，默认：{state.defaults.vendor}）。", [], None

    if form.step == "device_vendor":
        vendor = (text or state.defaults.vendor).lower()
        if vendor not in {"huawei", "ruijie"}:
            return "厂商仅支持 huawei 或 ruijie，请重新输入。", [], None
        form.current_device["vendor"] = vendor
        form.step = "device_host"
        return f"设备 {idx}：请输入管理 IP。", [], None

    if form.step == "device_host":
        if not text:
            return "管理 IP 不能为空。", [], None
        form.current_device["host"] = text
        form.step = "device_port"
        return f"设备 {idx}：请输入 SSH 端口（默认：{state.defaults.port}）。", [], None

    if form.step == "device_port":
        try:
            port = int(text or str(state.defaults.port))
            if port <= 0:
                raise ValueError
        except ValueError:
            return "SSH 端口格式错误，请输入正整数。", [], None
        form.current_device["port"] = str(port)
        form.step = "device_username"
        return f"设备 {idx}：请输入登录用户名（默认：{state.defaults.username}）。", [], None

    if form.step == "device_username":
        form.current_device["username"] = text or state.defaults.username
        form.step = "device_password"
        return f"设备 {idx}：请输入登录密码（回车表示使用配置文件默认密码）。", [], None

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
            return f"设备 {next_idx}：请输入设备名称（默认：device-{next_idx}）。", [], None

        inv = Inventory(
            site=form.site,
            contacts={"owner": form.owner, "phone": form.phone, "email": form.email},
            ai=state.ai,
            devices=form.devices,
        )
        return _start_job_manual_mode(state, inv, args, lock)

    return "流程状态异常，请输入“取消”后重新开始。", [], None


# ----------------------------
# live scanning (with progress)
# ----------------------------
def scan_subnet_live(
    cidr: str,
    port: int,
    timeout: float,
    on_progress: Callable[[int, int, int, int], None],
) -> list[str]:
    """
    返回 ssh_open_hosts(list[str])，并通过 on_progress 实时上报：
      scanned_ips, found_open, ssh_open, target_total
    这里 ssh_open == found_open（端口可达就算“可连”）
    """
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = list(net.hosts())
    target_total = len(hosts)

    scanned = 0
    open_cnt = 0
    ssh_open = 0
    ssh_hosts: list[str] = []

    for ip in hosts:
        scanned += 1
        ip_str = str(ip)

        ok = False
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((ip_str, port))
            ok = True
        except Exception:
            ok = False
        finally:
            try:
                s.close()
            except Exception:
                pass

        if ok:
            open_cnt += 1
            ssh_open += 1
            ssh_hosts.append(ip_str)

        on_progress(scanned, open_cnt, ssh_open, target_total)

    return ssh_hosts


# ----------------------------
# job runners
# ----------------------------
def _start_job_scan_mode(
    state: WebState, args: argparse.Namespace, lock: threading.Lock
) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
    form = state.form

    job_id = uuid.uuid4().hex[:10]
    job = JobState(job_id=job_id, status="running", phase="init", message="任务已创建，准备开始…")
    state.jobs[job_id] = job

    # 把表单必要参数“固化”出来（因为下面会 reset form）
    scan_cidr = form.scan_cidr
    scan_vendor = form.scan_vendor
    scan_port = form.scan_port
    scan_user = form.scan_username
    scan_pass = form.scan_password
    site = form.site
    contacts = {"owner": form.owner, "phone": form.phone, "email": form.email}

    # reset form so chat returns to normal
    state.form = ConversationForm()

    def worker() -> None:
        try:
            # phase scanning (live)
            with lock:
                j = state.jobs[job_id]
                j.phase = "scanning"
                j.message = f"正在扫描 {scan_cidr}（端口 {scan_port}）…"

            def _on_scan_progress(scanned_ips: int, found_open: int, ssh_open: int, target_total: int) -> None:
                with lock:
                    j = state.jobs[job_id]
                    j.scan_target_total = target_total
                    j.scanned_ips = scanned_ips
                    j.found_open = found_open
                    j.ssh_open = ssh_open
                    j.message = f"扫描中：{scanned_ips}/{target_total}，发现 {found_open}，SSH可连 {ssh_open}"

            ssh_hosts = scan_subnet_live(
                cidr=scan_cidr,
                port=scan_port,
                timeout=0.7,
                on_progress=_on_scan_progress,
            )

            devices = [
                DeviceConfig(
                    name=f"{scan_vendor}-auto-{i+1}",
                    vendor=scan_vendor,
                    host=h,
                    port=scan_port,
                    username=scan_user,
                    password=scan_pass,
                )
                for i, h in enumerate(ssh_hosts)
            ]

            inv = Inventory(site=site, contacts=contacts, ai=state.ai, devices=devices, subnet_cidr=scan_cidr)

            if not devices:
                with lock:
                    j = state.jobs[job_id]
                    j.status = "failed"
                    j.phase = "failed"
                    j.message = "扫描完成，但 SSH 可连接设备为 0，无法生成文档。"
                    j.finished_at = time.time()
                return

            _collect_and_generate_job(state, inv, args, lock, job_id)

        except Exception as exc:  # noqa: BLE001
            with lock:
                j = state.jobs[job_id]
                j.status = "failed"
                j.phase = "failed"
                j.message = f"任务失败：{exc}"
                j.finished_at = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return "已开始生成文档任务（后台执行中）。我会实时显示扫描/采集进度。", [], job_id


def _start_job_manual_mode(
    state: WebState, inventory: Inventory, args: argparse.Namespace, lock: threading.Lock
) -> Tuple[str, List[Dict[str, str]], Optional[str]]:
    job_id = uuid.uuid4().hex[:10]
    job = JobState(job_id=job_id, status="running", phase="init", message="任务已创建，准备开始…")
    state.jobs[job_id] = job

    # reset form
    state.form = ConversationForm()

    def worker() -> None:
        try:
            _collect_and_generate_job(state, inventory, args, lock, job_id)
        except Exception as exc:  # noqa: BLE001
            with lock:
                j = state.jobs[job_id]
                j.status = "failed"
                j.phase = "failed"
                j.message = f"任务失败：{exc}"
                j.finished_at = time.time()

    threading.Thread(target=worker, daemon=True).start()
    return "已开始生成文档任务（后台执行中）。我会实时显示采集/生成进度。", [], job_id


def _collect_and_generate_job(
    state: WebState, inventory: Inventory, args: argparse.Namespace, lock: threading.Lock, job_id: str
) -> None:
    # phase collecting (live)
    with lock:
        j = state.jobs[job_id]
        j.phase = "collecting"
        j.total_devices = len(inventory.devices)
        j.collected_ok = 0
        j.collected_failed = 0
        j.message = f"开始采集设备信息：共 {j.total_devices} 台…"

    snapshots = _collect_snapshots_web_with_progress(state, inventory, args.timeout, lock, job_id)

    with lock:
        state.inventory = inventory
        state.snapshots = snapshots

    if not snapshots:
        with lock:
            j = state.jobs[job_id]
            j.status = "failed"
            j.phase = "failed"
            j.message = "采集全部失败，无法生成文档。请检查网络与账号后重试。"
            j.finished_at = time.time()
        return

    # phase generating
    with lock:
        j = state.jobs[job_id]
        j.phase = "generating"
        j.message = "正在生成文档（写入 Markdown 文件）…"

    out_dir = Path(args.output)
    bundle = build_documents(inventory, snapshots)
    write_documents(bundle, out_dir)

    with lock:
        state.last_output_dir = out_dir
        links = [{"label": "下载 summary.md", "url": "/download/summary.md"}]
        links.extend(
            {"label": f"下载 {filename}", "url": f"/download/{filename}"}
            for filename in sorted(bundle.device_documents.keys())
        )

        j = state.jobs[job_id]
        j.download_links = links
        j.status = "done"
        j.phase = "done"
        j.message = f"已完成采集并生成文档（成功 {len(snapshots)} 台）。"
        j.finished_at = time.time()


def _collect_snapshots_web_with_progress(
    state: WebState, inventory: Inventory, timeout: int, lock: threading.Lock, job_id: str
) -> list:
    from paramiko.ssh_exception import AuthenticationException
    from iotmd.collectors.huawei import collect_huawei
    from iotmd.collectors.ruijie import collect_ruijie

    collectors = {"huawei": collect_huawei, "ruijie": collect_ruijie}
    snapshots: list = []

    total = len(inventory.devices)
    for i, device in enumerate(inventory.devices, start=1):
        with lock:
            j = state.jobs[job_id]
            j.message = f"采集中：{i}/{total}（{device.name} {device.host}）…"

        collector = collectors.get(device.vendor)
        if not collector:
            with lock:
                j = state.jobs[job_id]
                j.collected_failed += 1
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
            with lock:
                j = state.jobs[job_id]
                j.collected_ok += 1
        except AuthenticationException:
            with lock:
                j = state.jobs[job_id]
                j.collected_failed += 1
        except Exception:
            with lock:
                j = state.jobs[job_id]
                j.collected_failed += 1

        with lock:
            j = state.jobs[job_id]
            j.message = f"采集中：{i}/{total}，成功 {j.collected_ok}，失败 {j.collected_failed}"

    with lock:
        j = state.jobs[job_id]
        j.message = f"采集完成：成功 {j.collected_ok} 台，失败 {j.collected_failed} 台。"

    return snapshots


# ----------------------------
# HTML (UI): fixed-height chat + internal scrollbar + statusbar spinner
# ----------------------------
def _index_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>IotMd 对话助手</title>
  <style>
    :root {
      --bg:#0f172a; --panel:#111827; --text:#e5e7eb; --muted:#9ca3af;
      --user:#2563eb; --ai:#374151; --border:#334155; --card:#0b1220;
      --good:#86efac; --warn:#fbbf24; --bad:#f87171;
    }
    * { box-sizing:border-box; }
    body {
      margin:0; font-family:Inter,Arial,sans-serif;
      background:radial-gradient(circle at top left,#1f2937 0%,var(--bg) 45%);
      color:var(--text);
      height:100vh; display:flex; justify-content:center; align-items:stretch;
      padding:18px;
      overflow:hidden; /* 关键：禁止整页滚动，滚动发生在 chat 内 */
    }

    .app {
      width:min(1000px, 100%);
      height:calc(100vh - 36px); /* 关键：固定整体高度 */
      background:rgba(17,24,39,.95);
      border:1px solid var(--border);
      border-radius:16px;
      overflow:hidden;
      box-shadow:0 25px 60px rgba(0,0,0,.35);

      display:flex;
      flex-direction:column; /* header/status/chat/toolbar 垂直 */
      min-height:0;          /* 关键：允许子元素计算溢出 */
    }

    .header {
      padding:16px 18px;
      border-bottom:1px solid var(--border);
      flex: 0 0 auto;
    }
    .title { font-weight:700; }
    .muted { color:var(--muted); font-size:13px; margin-top:6px; line-height:1.4; }

    .statusbar {
      padding:12px 18px;
      border-bottom:1px solid var(--border);
      background:rgba(15,23,42,.55);
      display:none;
      gap:12px;
      align-items:center;
      flex: 0 0 auto;
    }
    .statusbar.show { display:flex; }
    .spinner {
      width:18px; height:18px; border-radius:999px;
      border:2px solid rgba(148,163,184,.35);
      border-top-color: rgba(96,165,250,.95);
      animation: spin .9s linear infinite;
      flex: 0 0 auto;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .statustext { display:flex; flex-direction:column; gap:4px; min-width:0; }
    .statusline { font-size:13px; color: var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .statusmeta { font-size:12px; color: var(--muted); display:flex; gap:10px; flex-wrap:wrap; }
    .pill { padding:2px 8px; border:1px solid rgba(148,163,184,.35); border-radius:999px; background:rgba(2,6,23,.25); }

    .chat {
      padding:18px;
      background:linear-gradient(180deg, rgba(17,24,39,.4), rgba(15,23,42,.4));
      display:flex;
      flex-direction:column;
      gap:10px;

      flex: 1 1 auto; /* 占满剩余高度 */
      min-height:0;   /* 关键：让 overflow 生效 */
      overflow-y:auto;

      scrollbar-width: thin;
    }
    .chat::-webkit-scrollbar { width: 10px; }
    .chat::-webkit-scrollbar-thumb { background: #475569; border-radius: 8px; }

    .bubble {
      max-width:78%;
      padding:12px 14px;
      border-radius:14px;
      white-space:pre-wrap;
      line-height:1.45;
      border:1px solid #475569;
    }
    .user { align-self:flex-end; background:var(--user); border-color:#60a5fa; }
    .ai { align-self:flex-start; background:var(--ai); }

    .toolbar {
      border-top:1px solid var(--border);
      padding:12px;
      display:grid;
      grid-template-columns:1fr auto;
      gap:10px;
      background:var(--panel);
      flex: 0 0 auto;
    }
    input[type=text] {
      width:100%;
      border:1px solid #475569;
      border-radius:10px;
      padding:12px;
      background:var(--card);
      color:var(--text);
      outline:none;
    }
    button {
      border:none;
      padding:9px 14px;
      border-radius:10px;
      cursor:pointer;
      color:white;
      background:#1f2937;
    }
    button:disabled { opacity:.55; cursor:not-allowed; }
    a.download { color:var(--good); text-decoration:none; font-weight:600; display:inline-block; margin-top:6px; }
  </style>
</head>
<body>
  <div class="app">
    <div class="header">
      <div class="title">IotMd 智能运维对话助手</div>
      <div class="muted">支持扫描网段自动发现交换机。优先读取 inventory.yaml 的 key 与默认账号密码。直接回车可采用默认值。</div>
    </div>

    <div id="statusbar" class="statusbar">
      <div class="spinner"></div>
      <div class="statustext">
        <div id="statusline" class="statusline">任务进行中…</div>
        <div class="statusmeta">
          <span id="pillPhase" class="pill">phase: -</span>
          <span id="pillScan" class="pill">scan: -</span>
          <span id="pillCollect" class="pill">collect: -</span>
        </div>
      </div>
    </div>

    <div id="chat" class="chat"></div>

    <div class="toolbar">
      <input id="msg" type="text" placeholder="输入消息（例如：生成文档 / 设置key sk-xxx / 帮助；可直接回车用默认值）" />
      <button id="sendBtn" onclick="sendMsg()">发送</button>
    </div>
  </div>

<script>
function scrollBottom(){
  const c=document.getElementById('chat');
  c.scrollTo({top:c.scrollHeight, behavior:'smooth'});
}
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

let activeJobId = null;
let jobTimer = null;

function setStatusVisible(visible) {
  const bar = document.getElementById('statusbar');
  if (visible) bar.classList.add('show');
  else bar.classList.remove('show');
}
function setStatus(line, phase, scanText, collectText) {
  document.getElementById('statusline').textContent = line || '任务进行中…';
  document.getElementById('pillPhase').textContent = `phase: ${phase || '-'}`;
  document.getElementById('pillScan').textContent = scanText || 'scan: -';
  document.getElementById('pillCollect').textContent = collectText || 'collect: -';
}

async function pollJob(jobId) {
  try {
    const resp = await fetch(`/api/job/${jobId}`);
    if (!resp.ok) return;
    const data = await resp.json();

    const scanText = (data.phase === 'scanning' || data.scannedIps || data.foundOpen || data.sshOpen)
      ? `scan: ${data.scannedIps||0}/${data.scanTargetTotal||0}, found ${data.foundOpen||0}, SSH ${data.sshOpen||0}`
      : 'scan: -';

    const collectText = (data.phase === 'collecting' || data.totalDevices || data.collectedOk || data.collectedFailed)
      ? `collect: ok ${data.collectedOk||0}/${data.totalDevices||0}, fail ${data.collectedFailed||0}`
      : 'collect: -';

    setStatusVisible(true);
    setStatus(data.message, data.phase, scanText, collectText);

    if (data.status === 'done' || data.status === 'failed') {
      clearInterval(jobTimer);
      jobTimer = null;
      activeJobId = null;

      addBubble(data.message || (data.status === 'done' ? '完成' : '失败'), 'ai', data.downloadLinks || []);
      setTimeout(()=>setStatusVisible(false), data.status === 'done' ? 1500 : 800);
    }
  } catch (e) {}
}

function startPolling(jobId) {
  activeJobId = jobId;
  if (jobTimer) clearInterval(jobTimer);
  jobTimer = setInterval(()=>pollJob(jobId), 400); // 更快一点更“实时”
  pollJob(jobId);
}

async function sendMsg(forceDefault=false) {
  const input = document.getElementById('msg');
  const btn = document.getElementById('sendBtn');

  const raw = input.value;
  const message = forceDefault ? '__DEFAULT__' : raw;
  if (!forceDefault && !raw.trim()) return;

  if (!forceDefault) addBubble(raw, 'user');
  else addBubble('（使用默认值）', 'user');

  input.value = '';
  btn.disabled = true;

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message})
    });
    const data = await resp.json();

    addBubble(data.reply || data.error || '无响应', 'ai', data.downloadLinks || []);

    if (data.jobId) {
      setStatusVisible(true);
      setStatus('任务已启动，正在获取进度…', 'init', 'scan: -', 'collect: -');
      startPolling(data.jobId);
    }
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('msg').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const raw = document.getElementById('msg').value;
    if (!raw.trim()) sendMsg(true);
    else sendMsg(false);
  }
});

addBubble('你好，我是 IotMd 助手,输入“生成文档”进入采集流程。', 'ai');
</script>
</body>
</html>
"""


# ----------------------------
# (optional) CLI entry remains up to your existing main
# ----------------------------
