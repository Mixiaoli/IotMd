from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import importlib
import importlib.util

if importlib.util.find_spec("yaml") is not None:
    yaml = importlib.import_module("yaml")
else:
    yaml = None


@dataclass(frozen=True)
class AiConfig:
    enabled: bool
    api_base: str
    model: str
    api_key: str | None = None


@dataclass(frozen=True)
class DeviceConfig:
    name: str
    vendor: str
    host: str
    port: int
    username: str
    password: str


@dataclass(frozen=True)
class SubnetHost:
    host: str
    online: bool
    ssh_open: bool
    remark: str = ""


@dataclass(frozen=True)
class Inventory:
    site: str
    contacts: dict[str, str]
    ai: AiConfig
    devices: list[DeviceConfig]
    subnet_cidr: str | None = None
    subnet_hosts: list[SubnetHost] = field(default_factory=list)


def load_inventory(path: str | Path) -> Inventory:
    if yaml is None:
        raise RuntimeError("缺少 pyyaml 依赖，请先安装 pyyaml")
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
        api_key=str(ai_data.get("api_key")) if ai_data.get("api_key") else None,
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
