from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AiConfig:
    enabled: bool
    api_base: str
    model: str


@dataclass(frozen=True)
class DeviceConfig:
    name: str
    vendor: str
    host: str
    port: int
    username: str
    password: str


@dataclass(frozen=True)
class Inventory:
    site: str
    contacts: dict[str, str]
    ai: AiConfig
    devices: list[DeviceConfig]


def load_inventory(path: str | Path) -> Inventory:
    data: dict[str, Any]
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    ai_data = data.get("ai", {})
    ai = AiConfig(
        enabled=bool(ai_data.get("enabled", False)),
        api_base=str(
            ai_data.get(
                "api_base",
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            )
        ),
        model=str(ai_data.get("model", "qwen-turbo")),
    )

    devices = [
        DeviceConfig(
            name=str(item["name"]),
            vendor=str(item["vendor"]).lower(),
            host=str(item["host"]),
            port=int(item.get("port", 22)),
            username=str(item["username"]),
            password=str(item["password"]),
        )
        for item in data.get("devices", [])
    ]

    return Inventory(
        site=str(data.get("site", "unknown-site")),
        contacts=dict(data.get("contacts", {})),
        ai=ai,
        devices=devices,
    )
