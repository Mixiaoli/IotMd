from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceSnapshot:
    name: str
    vendor: str
    config: str
    lldp: str
    interfaces: str
