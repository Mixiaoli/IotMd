from __future__ import annotations

import argparse
from pathlib import Path

from paramiko.ssh_exception import AuthenticationException

from iotmd.ai import resolve_api_key
from iotmd.collectors import DeviceSnapshot
from iotmd.collectors.huawei import collect_huawei
from iotmd.collectors.ruijie import collect_ruijie
from iotmd.config import load_inventory
from iotmd.generator import build_documents, write_documents
from iotmd.interactive import prompt_credentials, prompt_inventory, prompt_yes_no


COLLECTORS = {
    "huawei": collect_huawei,
    "ruijie": collect_ruijie,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="IotMd 文档自动生成工具")
    parser.add_argument(
        "--inventory",
        default="examples/inventory.yaml",
        help="设备清单 YAML 文件路径",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="交互式输入设备信息并生成文档",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="生成文档输出目录",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="设备采集超时时间（秒）",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="单台设备采集失败时继续处理其他设备",
    )

    args = parser.parse_args()
    inventory = (
        prompt_inventory()
        if args.interactive
        else load_inventory(Path(args.inventory))
    )
    if inventory.ai.enabled and not resolve_api_key(inventory.ai.api_key):
        print("AI 总结已开启，但未检测到 DASHSCOPE_API_KEY，已回退到默认摘要。")

    snapshots: list[DeviceSnapshot] = []
    for device in inventory.devices:
        collector = COLLECTORS.get(device.vendor)
        if not collector:
            raise ValueError(f"不支持的设备厂商: {device.vendor}")
        print(f"开始采集 {device.name} ({device.vendor}) {device.host}:{device.port} ...")
        username = device.username
        password = device.password
        while True:
            try:
                snapshots.append(
                    collector(
                        name=device.name,
                        host=device.host,
                        port=device.port,
                        username=username,
                        password=password,
                        timeout=args.timeout,
                    )
                )
                print(f"完成采集 {device.name}")
                break
            except AuthenticationException as exc:
                print(f"认证失败 {device.name}: {exc}")
                if args.interactive and prompt_yes_no("是否重新输入账号密码 (y/n)", default="y"):
                    username, password = prompt_credentials(
                        inventory.ai,
                        device_name=device.name,
                        default_username=username,
                    )
                    continue
                if not args.continue_on_error:
                    raise
                break
            except Exception as exc:  # noqa: BLE001
                print(f"采集失败 {device.name}: {exc}")
                if not args.continue_on_error:
                    raise
                break

    if snapshots:
        bundle = build_documents(inventory, snapshots)
        write_documents(bundle, args.output)
        print(f"已生成文档到 {args.output}")
    else:
        print("未采集到任何设备数据，未生成文档。")


if __name__ == "__main__":
    main()
