from __future__ import annotations

import argparse
from pathlib import Path

from iotmd.ai import resolve_api_key
from iotmd.chat import ChatContext, run_chat_loop
from iotmd.config import AiConfig, Inventory, load_inventory
from iotmd.generator import build_documents, write_documents
from iotmd.interactive import prompt_ai_config, prompt_inventory
from iotmd.web import run_web


# 函数说明: main 的核心用途见函数实现逻辑。
def main() -> None:
    """解析命令行参数并分发到批处理、交互式或 Web 模式。"""
    parser = argparse.ArgumentParser(description="IotMd 文档自动生成工具")
    parser.add_argument("--inventory", default="examples/inventory.yaml", help="设备清单 YAML 文件路径")
    parser.add_argument("--interactive", action="store_true", help="交互式输入设备信息并生成文档")
    parser.add_argument("--output", default="output", help="生成文档输出目录")
    parser.add_argument("--timeout", type=int, default=15, help="设备采集超时时间（秒）")
    parser.add_argument("--continue-on-error", action="store_true", help="单台设备采集失败时继续处理其他设备")
    parser.add_argument("--web", action="store_true", help="启动简易 Web 对话与文档页面")
    parser.add_argument("--host", default="127.0.0.1", help="Web 服务监听地址")
    parser.add_argument("--port", type=int, default=8765, help="Web 服务端口")

    args = parser.parse_args()
    if args.web:
        run_web(args)
        return
    if args.interactive:
        _interactive_flow(args)
        return

    inventory = load_inventory(Path(args.inventory))
    _warn_ai_key(inventory)
    snapshots = _collect_snapshots(args, inventory)
    _finalize_documents(args, inventory, snapshots)


# 函数说明: _interactive_flow 的核心用途见函数实现逻辑。
def _interactive_flow(args: argparse.Namespace) -> None:
    """处理交互式分支，支持先采集设备或直接进入 AI 对话。"""
    _print_welcome()
    choice = input("是否要生成交换机文档 (y/n): ").strip().lower()
    if choice == "y":
        inventory = prompt_inventory()
        _warn_ai_key(inventory)
        snapshots = _collect_snapshots(args, inventory)
        _finalize_documents(args, inventory, snapshots)
        _start_chat(args, inventory.ai, snapshots=snapshots, inventory=inventory)
        return

    ai = prompt_ai_config()
    if choice not in {"n", ""}:
        print("无效输入，已进入自然语言对话模式。")
    _start_chat(args, ai, snapshots=[], inventory=None)


# 函数说明: _start_chat 的核心用途见函数实现逻辑。
def _start_chat(
    args: argparse.Namespace,
    ai: AiConfig,
    snapshots: list,
    inventory: Inventory | None,
) -> None:
    """构建统一聊天上下文，避免重复创建 ChatContext 代码。"""
    run_chat_loop(
        ChatContext(
            ai=ai,
            snapshots=snapshots,
            inventory=inventory,
            load_data=lambda: _load_data(args),
            generate_docs=lambda inv, snaps: _finalize_documents(args, inv, snaps),
        )
    )


# 函数说明: _collect_snapshots 的核心用途见函数实现逻辑。
def _collect_snapshots(args: argparse.Namespace, inventory: Inventory) -> list:
    """按设备厂商调用对应采集器，返回可用于文档生成的数据快照。"""
    from paramiko.ssh_exception import AuthenticationException

    from iotmd.collectors.huawei import collect_huawei
    from iotmd.collectors.ruijie import collect_ruijie

    collectors = {"huawei": collect_huawei, "ruijie": collect_ruijie}
    snapshots: list = []

    for device in inventory.devices:
        collector = collectors.get(device.vendor)
        if not collector:
            raise ValueError(f"不支持的设备厂商: {device.vendor}")

        print(f"开始采集 {device.name} ({device.vendor}) {device.host}:{device.port} ...")
        try:
            snapshots.append(
                collector(
                    name=device.name,
                    host=device.host,
                    port=device.port,
                    username=device.username,
                    password=device.password,
                    timeout=args.timeout,
                )
            )
            print(f"完成采集 {device.name}")
        except AuthenticationException as exc:
            print(f"认证失败 {device.name}: {exc}")
            if args.interactive:
                print(f"已跳过 {device.name}，继续采集下一台设备。")
                continue
            if not args.continue_on_error:
                raise
        except Exception as exc:  # noqa: BLE001
            print(f"采集失败 {device.name}: {exc}")
            if args.interactive:
                print(f"已跳过 {device.name}，继续采集下一台设备。")
                continue
            if not args.continue_on_error:
                raise

    return snapshots


# 函数说明: _finalize_documents 的核心用途见函数实现逻辑。
def _finalize_documents(args: argparse.Namespace, inventory: Inventory, snapshots: list) -> None:
    """根据采集结果生成并落盘 Markdown 文档。"""
    if not snapshots:
        print("未采集到任何设备数据，未生成文档。")
        return
    bundle = build_documents(inventory, snapshots)
    write_documents(bundle, args.output)
    print(f"已生成文档到 {args.output}")


# 函数说明: _load_data 的核心用途见函数实现逻辑。
def _load_data(args: argparse.Namespace) -> tuple[Inventory, list]:
    """交互式加载设备配置并执行采集，供聊天流程复用。"""
    inventory = prompt_inventory()
    _warn_ai_key(inventory)
    snapshots = _collect_snapshots(args, inventory)
    return inventory, snapshots


# 函数说明: _warn_ai_key 的核心用途见函数实现逻辑。
def _warn_ai_key(inventory: Inventory) -> None:
    """在启用 AI 但缺少密钥时提示将回退默认摘要。"""
    if inventory.ai.enabled and not resolve_api_key(inventory.ai.api_key):
        print("AI 总结已开启，但未检测到 DASHSCOPE_API_KEY，已回退到默认摘要。")


# 函数说明: _print_welcome 的核心用途见函数实现逻辑。
def _print_welcome() -> None:
    """打印交互模式欢迎语。"""
    print("\n欢迎使用 IotMd 运维助手。你可以先进行自然语言交互，也可以选择生成交换机文档。")


if __name__ == "__main__":
    main()
