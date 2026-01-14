from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from iotmd.ai import answer_query
from iotmd.collectors import DeviceSnapshot
from iotmd.config import AiConfig


@dataclass(frozen=True)
class ChatContext:
    ai: AiConfig
    snapshots: list[DeviceSnapshot]


def run_chat_loop(context: ChatContext) -> None:
    print("\n进入自然语言运维助手，输入 'exit' 结束。")
    while True:
        query = input("\n请输入问题: ").strip()
        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            print("已退出自然语言交互。")
            break
        response = answer_query(query, context.snapshots, context.ai)
        print(f"\n{response}")


def format_snapshot_summary(snapshots: Iterable[DeviceSnapshot]) -> str:
    lines = []
    for snapshot in snapshots:
        lines.append(f"设备: {snapshot.name} ({snapshot.vendor})")
        if snapshot.interfaces.strip():
            lines.append("接口概览:")
            lines.append(snapshot.interfaces.strip())
        if snapshot.lldp.strip():
            lines.append("LLDP 邻居:")
            lines.append(snapshot.lldp.strip())
        lines.append("")
    return "\n".join(lines)
