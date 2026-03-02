from __future__ import annotations

import os

from iotmd.ai import build_ai_question
from iotmd.config import AiConfig, DeviceConfig, Inventory, SubnetHost
from iotmd.discovery import scan_subnet


# 函数说明: prompt_inventory 的核心用途见函数实现逻辑。
def prompt_inventory() -> Inventory:
    ai = prompt_ai_config()

    site = _prompt(_ask(ai, "站点名称"), default="HQ")
    owner = _prompt(_ask(ai, "负责人"), default="NetOps")
    phone = _prompt(_ask(ai, "联系电话"), default="")
    email = _prompt(_ask(ai, "联系邮箱"), default="")

    devices: list[DeviceConfig]
    subnet_cidr: str | None = None
    subnet_hosts: list[SubnetHost] = []
    if prompt_yes_no("是否按网段自动发现设备 (y/n)", default="n"):
        devices, subnet_cidr, subnet_hosts = _prompt_discovered_devices(ai)
    else:
        devices = _prompt_manual_devices(ai)

    return Inventory(
        site=site,
        contacts={"owner": owner, "phone": phone, "email": email},
        ai=ai,
        devices=devices,
        subnet_cidr=subnet_cidr,
        subnet_hosts=subnet_hosts,
    )


# 函数说明: _prompt_manual_devices 的核心用途见函数实现逻辑。
def _prompt_manual_devices(ai: AiConfig) -> list[DeviceConfig]:
    device_count = int(_prompt(_ask(ai, "设备数量"), default="1"))
    devices: list[DeviceConfig] = []

    for index in range(device_count):
        print(f"\n设备 {index + 1}")
        name = _prompt(_ask(ai, "设备名称"), default=f"device-{index + 1}")
        vendor = _prompt(_ask(ai, "厂商 (huawei/ruijie)"), default="huawei").lower()
        host = _prompt(_ask(ai, "管理 IP"), default="192.0.2.1")
        port = int(_prompt(_ask(ai, "SSH 端口"), default="22"))
        username, password = prompt_credentials(ai, device_name=name, default_username="admin")
        devices.append(
            DeviceConfig(
                name=name,
                vendor=vendor,
                host=host,
                port=port,
                username=username,
                password=password,
            )
        )
    return devices


# 函数说明: _prompt_discovered_devices 的核心用途见函数实现逻辑。
def _prompt_discovered_devices(ai: AiConfig) -> tuple[list[DeviceConfig], str, list[SubnetHost]]:
    cidr = _prompt(_ask(ai, "网段 CIDR"), default="10.133.12.0/24")
    vendor = _prompt(_ask(ai, "发现设备厂商 (huawei/ruijie)"), default="huawei").lower()
    port = int(_prompt(_ask(ai, "SSH 端口"), default="22"))
    timeout = float(_prompt(_ask(ai, "Ping/端口探测超时(秒)"), default="0.8"))
    prefix = _prompt(_ask(ai, "设备名称前缀"), default="auto-device")
    username, password = prompt_credentials(ai, device_name="批量发现设备", default_username="admin")

    print(f"开始扫描网段 {cidr} ...")
    subnet_hosts = scan_subnet(cidr=cidr, ssh_port=port, timeout=timeout)
    online = [item for item in subnet_hosts if item.online]
    ssh_ok = [item for item in subnet_hosts if item.ssh_open]
    print(f"扫描完成，总计 {len(subnet_hosts)} 个IP，Ping 通 {len(online)} 个，SSH 可达 {len(ssh_ok)} 个")

    devices: list[DeviceConfig] = []
    for index, item in enumerate(ssh_ok, start=1):
        devices.append(
            DeviceConfig(
                name=f"{prefix}-{index}",
                vendor=vendor,
                host=item.host,
                port=port,
                username=username,
                password=password,
            )
        )
    return devices, cidr, subnet_hosts


# 函数说明: prompt_ai_config 的核心用途见函数实现逻辑。
def prompt_ai_config() -> AiConfig:
    ai_key = os.environ.get("DASHSCOPE_API_KEY")
    if not ai_key:
        ai_key = _prompt(
            "DASHSCOPE_API_KEY (留空则读取环境变量)",
            default="",
        ) or None

    ai = AiConfig(
        enabled=True,
        api_base="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        model="qwen-turbo",
        api_key=ai_key,
    )
    if not ai.api_key:
        print("未检测到 DASHSCOPE_API_KEY，将仅使用默认问题与摘要。")
    return ai


# 函数说明: _prompt 的核心用途见函数实现逻辑。
def _prompt(label: str, default: str) -> str:
    value = input(f"{label} (默认: {default}): ").strip()
    return value or default


# 函数说明: prompt_yes_no 的核心用途见函数实现逻辑。
def prompt_yes_no(label: str, default: str = "y") -> bool:
    value = _prompt(label, default=default).lower()
    return value == "y"


# 函数说明: prompt_credentials 的核心用途见函数实现逻辑。
def prompt_credentials(
    ai: AiConfig,
    device_name: str,
    default_username: str,
) -> tuple[str, str]:
    username = _prompt(_ask(ai, f"{device_name} 账号"), default=default_username)
    password = _prompt(_ask(ai, f"{device_name} 密码"), default="")
    return username, password


# 函数说明: _ask 的核心用途见函数实现逻辑。
def _ask(ai: AiConfig, label: str) -> str:
    if not ai.enabled:
        return label
    try:
        return build_ai_question(label, ai.api_base, ai.model, ai.api_key)
    except Exception:
        return label
