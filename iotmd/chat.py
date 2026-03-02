from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from iotmd.ai import answer_query
from iotmd.collectors import DeviceSnapshot
from iotmd.config import AiConfig, Inventory


@dataclass
class ChatContext:
    """封装聊天会话依赖，便于 CLI 与 Web 复用同一套流程。"""

    ai: AiConfig
    snapshots: list[DeviceSnapshot]
    inventory: Inventory | None = None
    load_data: Callable[[], tuple[Inventory, list[DeviceSnapshot]]] | None = None
    generate_docs: Callable[[Inventory, list[DeviceSnapshot]], None] | None = None


# 函数说明: run_chat_loop 的核心用途见函数实现逻辑。
def run_chat_loop(context: ChatContext) -> None:
    """启动命令行问答循环，并处理内置控制指令。"""
    _print_welcome()
    while True:
        query = input("\n请输入问题: ").strip()
        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            print("已退出自然语言交互。")
            break
        if query in {"生成文档", "生成交换机文档", "生成网络文档"}:
            _handle_generate_docs(context)
            continue
        if query in {"加载设备", "输入设备", "导入设备"}:
            _handle_load_devices(context)
            continue
        if query.lower() in {"help", "帮助"}:
            _print_help()
            continue
        response = answer_query(query, context.snapshots, context.ai)
        print(f"\n{response}")


# 函数说明: _print_welcome 的核心用途见函数实现逻辑。
def _print_welcome() -> None:
    """输出聊天欢迎语并展示可用命令。"""
    print(
        "\n你好，我是你的运维 AI 助手。你可以自然语言提问，或输入“生成文档”来输出交换机文档。"
    )
    _print_help()


# 函数说明: _print_help 的核心用途见函数实现逻辑。
def _print_help() -> None:
    """打印聊天模式内置指令说明。"""
    print(
        "\n可用指令:\n"
        "- 生成文档 / 生成交换机文档\n"
        "- 加载设备 / 输入设备\n"
        "- 帮助\n"
        "- exit 退出\n"
    )


# 函数说明: _handle_load_devices 的核心用途见函数实现逻辑。
def _handle_load_devices(context: ChatContext) -> None:
    """触发交互式设备加载并更新当前会话上下文。"""
    if not context.load_data:
        print("当前未配置设备加载入口。")
        return
    inventory, snapshots = context.load_data()
    context.inventory = inventory
    context.ai = inventory.ai
    context.snapshots = snapshots
    if snapshots:
        print("已加载设备数据，可以继续提问或生成文档。")
    else:
        print("未采集到设备数据。")


# 函数说明: _handle_generate_docs 的核心用途见函数实现逻辑。
def _handle_generate_docs(context: ChatContext) -> None:
    """在必要时先加载设备数据，再执行文档生成动作。"""
    if not context.generate_docs or not context.load_data:
        print("当前未配置文档生成入口。")
        return
    if not context.snapshots or not context.inventory:
        inventory, snapshots = context.load_data()
        context.inventory = inventory
        context.ai = inventory.ai
        context.snapshots = snapshots
    context.generate_docs(context.inventory, context.snapshots)
