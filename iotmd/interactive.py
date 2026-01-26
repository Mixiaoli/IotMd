from __future__ import annotations

from dataclasses import dataclass

import os

from iotmd.ai import build_ai_question
from iotmd.config import AiConfig, DeviceConfig, Inventory


@dataclass(frozen=True)
class InteractiveAnswers:
    site: str
    contacts: dict[str, str]
    devices: list[DeviceConfig]
    ai: AiConfig


def prompt_inventory() -> Inventory:
    ai = prompt_ai_config()

    site = _prompt(_ask(ai, "站点名称"), default="HQ")
    owner = _prompt(_ask(ai, "负责人"), default="NetOps")
    phone = _prompt(_ask(ai, "联系电话"), default="")
    email = _prompt(_ask(ai, "联系邮箱"), default="")

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

    return Inventory(
        site=site,
        contacts={"owner": owner, "phone": phone, "email": email},
        ai=ai,
        devices=devices,
    )


def prompt_ai_config() -> AiConfig:
    ai_enabled = _prompt("是否启用 AI 总结 (y/n)", default="n").lower() == "y"
    ai_key = None
    if ai_enabled:
        ai_key = _prompt(
            "DASHSCOPE_API_KEY (留空则读取环境变量)",
            default=os.environ.get("DASHSCOPE_API_KEY", ""),
        ) or None

    ai = AiConfig(
        enabled=ai_enabled,
        api_base="https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        model="qwen-turbo",
        api_key=ai_key,
    )
    if ai.enabled and not ai.api_key:
        print("AI 已开启但未提供 API Key，将仅使用默认问题与摘要。")
    return ai


def _prompt(label: str, default: str) -> str:
    value = input(f"{label} (默认: {default}): ").strip()
    return value or default


def prompt_yes_no(label: str, default: str = "y") -> bool:
    value = _prompt(label, default=default).lower()
    return value == "y"


def prompt_credentials(
    ai: AiConfig,
    device_name: str,
    default_username: str,
) -> tuple[str, str]:
    username = _prompt(_ask(ai, f"{device_name} 账号"), default=default_username)
    password = _prompt(_ask(ai, f"{device_name} 密码"), default="")
    return username, password


def _ask(ai: AiConfig, label: str) -> str:
    if not ai.enabled:
        return label
    try:
        return build_ai_question(label, ai.api_base, ai.model, ai.api_key)
    except Exception:
        return label
