from __future__ import annotations

import re
from dataclasses import dataclass

from iotmd.collectors import DeviceSnapshot


@dataclass(frozen=True)
class TopologyLink:
    local_device: str
    local_port: str
    remote_device: str
    remote_port: str


# 函数说明: build_topology 的核心用途见函数实现逻辑。
def build_topology(snapshots: list[DeviceSnapshot]) -> list[TopologyLink]:
    links: list[TopologyLink] = []
    for snapshot in snapshots:
        links.extend(_parse_lldp(snapshot))
    return _dedupe_links(links)


# 函数说明: render_mermaid 的核心用途见函数实现逻辑。
def render_mermaid(links: list[TopologyLink]) -> str:
    lines = ["graph LR"]
    for link in links:
        left = f"{link.local_device}({link.local_device})"
        right = f"{link.remote_device}({link.remote_device})"
        lines.append(
            f"    {left} -- {link.local_port} ↔ {link.remote_port} --> {right}"
        )
    return "\n".join(lines)


# 函数说明: _parse_lldp 的核心用途见函数实现逻辑。
def _parse_lldp(snapshot: DeviceSnapshot) -> list[TopologyLink]:
    if snapshot.vendor == "huawei":
        return _parse_huawei_lldp(snapshot)
    if snapshot.vendor == "ruijie":
        return _parse_ruijie_lldp(snapshot)
    return []


# 函数说明: _parse_huawei_lldp 的核心用途见函数实现逻辑。
def _parse_huawei_lldp(snapshot: DeviceSnapshot) -> list[TopologyLink]:
    # Huawei output typically includes lines like:
    # GigabitEthernet0/0/1  DeviceA  GigabitEthernet0/0/24
    pattern = re.compile(
        r"^(?P<local>\S+)\s+(?P<remote>\S+)\s+(?P<remote_port>\S+)",
        re.MULTILINE,
    )
    links = []
    for match in pattern.finditer(snapshot.lldp):
        links.append(
            TopologyLink(
                local_device=snapshot.name,
                local_port=match.group("local"),
                remote_device=match.group("remote"),
                remote_port=match.group("remote_port"),
            )
        )
    return links


# 函数说明: _parse_ruijie_lldp 的核心用途见函数实现逻辑。
def _parse_ruijie_lldp(snapshot: DeviceSnapshot) -> list[TopologyLink]:
    # Ruijie output often includes columns like:
    # Local Interface  Chassis ID  Port ID  System Name
    pattern = re.compile(
        r"^(?P<local>\S+)\s+\S+\s+(?P<remote_port>\S+)\s+(?P<remote>\S+)",
        re.MULTILINE,
    )
    links = []
    for match in pattern.finditer(snapshot.lldp):
        links.append(
            TopologyLink(
                local_device=snapshot.name,
                local_port=match.group("local"),
                remote_device=match.group("remote"),
                remote_port=match.group("remote_port"),
            )
        )
    return links


# 函数说明: _dedupe_links 的核心用途见函数实现逻辑。
def _dedupe_links(links: list[TopologyLink]) -> list[TopologyLink]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[TopologyLink] = []
    for link in links:
        key = (link.local_device, link.local_port, link.remote_device, link.remote_port)
        reverse = (link.remote_device, link.remote_port, link.local_device, link.local_port)
        if key in seen or reverse in seen:
            continue
        seen.add(key)
        unique.append(link)
    return unique
