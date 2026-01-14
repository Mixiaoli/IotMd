from __future__ import annotations

from dataclasses import dataclass

from iotmd.config import AiConfig, DeviceConfig, Inventory


@dataclass(frozen=True)
class InteractiveAnswers:
    site: str
    contacts: dict[str, str]
    devices: list[DeviceConfig]
    ai: AiConfig


def prompt_inventory() -> Inventory:
    site = _prompt("站点名称", default="HQ")
    owner = _prompt("负责人", default="NetOps")
    phone = _prompt("联系电话", default="")
    email = _prompt("联系邮箱", default="")

    device_count = int(_prompt("设备数量", default="1"))
    devices: list[DeviceConfig] = []
    for index in range(device_count):
        print(f"\n设备 {index + 1}")
        name = _prompt("设备名称", default=f"device-{index + 1}")
        vendor = _prompt("厂商 (huawei/ruijie)", default="huawei").lower()
        host = _prompt("管理 IP", default="192.0.2.1")
        port = int(_prompt("SSH 端口", default="22"))
        username = _prompt("账号", default="admin")
        password = _prompt("密码", default="")
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

    ai_enabled = _prompt("是否启用 AI 总结 (y/n)", default="n").lower() == "y"
    ai = AiConfig(
        enabled=ai_enabled,
        api_base="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        model="qwen-turbo",
    )

    return Inventory(
        site=site,
        contacts={"owner": owner, "phone": phone, "email": email},
        ai=ai,
        devices=devices,
    )


def _prompt(label: str, default: str) -> str:
    value = input(f"{label} (默认: {default}): ").strip()
    return value or default
