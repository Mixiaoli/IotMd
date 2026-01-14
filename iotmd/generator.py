from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from iotmd.ai import AiSummary, summarize_device
from iotmd.collectors import DeviceSnapshot
from iotmd.config import Inventory
from iotmd.topology import build_topology, render_mermaid


@dataclass(frozen=True)
class DocumentBundle:
    overview: str
    topology: str
    devices: str


def build_documents(inventory: Inventory, snapshots: list[DeviceSnapshot]) -> DocumentBundle:
    summaries = [
        summarize_device(
            snapshot,
            inventory.ai.api_base,
            inventory.ai.model,
            inventory.ai.enabled,
            inventory.ai.api_key,
        )
        for snapshot in snapshots
    ]

    overview = _render_overview(inventory, summaries)
    topology_links = build_topology(snapshots)
    topology = _render_topology(topology_links)
    devices = _render_device_details(snapshots, summaries)

    return DocumentBundle(overview=overview, topology=topology, devices=devices)


def write_documents(bundle: DocumentBundle, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    (output_path / "overview.md").write_text(bundle.overview, encoding="utf-8")
    (output_path / "topology.md").write_text(bundle.topology, encoding="utf-8")
    (output_path / "devices.md").write_text(bundle.devices, encoding="utf-8")


def _render_overview(inventory: Inventory, summaries: list[AiSummary]) -> str:
    lines = [
        f"# {inventory.site} 运维文档总览",
        "",
        "## 负责人",
    ]
    for key, value in inventory.contacts.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## 设备摘要"])
    for summary in summaries:
        lines.append(f"- **{summary.device_name}**: {summary.summary}")

    return "\n".join(lines) + "\n"


def _render_topology(links: list) -> str:
    mermaid = render_mermaid(links)
    return "\n".join([
        "# 网络拓扑",
        "",
        "```mermaid",
        mermaid,
        "```",
        "",
    ])


def _render_device_details(
    snapshots: list[DeviceSnapshot], summaries: list[AiSummary]
) -> str:
    summary_map = {summary.device_name: summary.summary for summary in summaries}
    sections = ["# 设备详细信息", ""]

    for snapshot in snapshots:
        sections.extend(
            [
                f"## {snapshot.name} ({snapshot.vendor})",
                "",
                f"摘要: {summary_map.get(snapshot.name, '')}",
                "",
                "### 接口概览",
                "```",
                snapshot.interfaces.strip(),
                "```",
                "",
                "### 配置",
                "```",
                snapshot.config.strip(),
                "```",
                "",
                "### LLDP 邻居",
                "```",
                snapshot.lldp.strip(),
                "```",
                "",
            ]
        )

    return "\n".join(sections)
