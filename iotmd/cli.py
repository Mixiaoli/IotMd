from __future__ import annotations

import argparse
from pathlib import Path

from iotmd.collectors import DeviceSnapshot
from iotmd.collectors.huawei import collect_huawei
from iotmd.collectors.ruijie import collect_ruijie
from iotmd.config import load_inventory
from iotmd.generator import build_documents, write_documents


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
        "--output",
        default="output",
        help="生成文档输出目录",
    )

    args = parser.parse_args()
    inventory = load_inventory(Path(args.inventory))

    snapshots: list[DeviceSnapshot] = []
    for device in inventory.devices:
        collector = COLLECTORS.get(device.vendor)
        if not collector:
            raise ValueError(f"不支持的设备厂商: {device.vendor}")
        snapshots.append(
            collector(
                name=device.name,
                host=device.host,
                port=device.port,
                username=device.username,
                password=device.password,
            )
        )

    bundle = build_documents(inventory, snapshots)
    write_documents(bundle, args.output)
    print(f"已生成文档到 {args.output}")


if __name__ == "__main__":
    main()
