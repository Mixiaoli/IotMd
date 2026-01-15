from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from iotmd.ai import answer_query
from iotmd.collectors import DeviceSnapshot
from iotmd.config import AiConfig


@dataclass(frozen=True)
class ChatContext:
    ai: AiConfig
    snapshots: list[DeviceSnapshot]
    generate_docs: Callable[[], None] | None = None


def run_chat_loop(context: ChatContext) -> None:
    _print_welcome()
    while True:
        query = input("\n请输入问题: ").strip()
        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            print("已退出自然语言交互。")
            break
        if query in {"生成文档", "生成交换机文档", "生成网络文档"}:
            if context.generate_docs:
                context.generate_docs()
            else:
                print("当前未配置文档生成入口。")
            continue
        if query.lower() in {"help", "帮助"}:
            _print_help()
            continue
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


def _print_welcome() -> None:
    print(
        "\n你好，我是你的运维 AI 助手。你可以自然语言提问，或输入“生成文档”来输出交换机文档。"
    )
    _print_help()


def _print_help() -> None:
    print(
        "\n可用指令:\n"
        "- 生成文档 / 生成交换机文档\n"
        "- 帮助\n"
        "- exit 退出\n"
    )
