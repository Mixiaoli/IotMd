#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_device_snapshots(input_dir: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            snapshots.append(json.load(handle))
    return snapshots


def normalize_link_key(
    source: str,
    target: str,
    local_interface: str,
    remote_interface: str,
) -> tuple[str, str, str, str]:
    devices = tuple(sorted([source, target]))
    interfaces = tuple(sorted([local_interface, remote_interface]))
    return devices[0], devices[1], interfaces[0], interfaces[1]


def build_topology(
    snapshots: list[dict[str, Any]],
    company: str,
    region: str,
    description: str,
) -> dict[str, Any]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for device in snapshots:
        source = device.get("name", "")
        for neighbor in device.get("neighbors", []):
            target = neighbor.get("device", "")
            local_interface = neighbor.get("local_interface", "")
            remote_interface = neighbor.get("remote_interface", "")
            key = normalize_link_key(source, target, local_interface, remote_interface)
            if key in seen:
                continue
            seen.add(key)
            links.append(
                {
                    "source": source,
                    "target": target,
                    "medium": neighbor.get("medium", ""),
                    "note": neighbor.get("note", ""),
                }
            )

    return {
        "company": company,
        "region": region,
        "description": description,
        "topology": {"links": links},
        "devices": snapshots,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据设备采集快照生成公司网络拓扑 JSON"
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="设备采集快照所在目录（JSON 文件）",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出拓扑 JSON 文件路径",
    )
    parser.add_argument(
        "--company",
        required=True,
        help="公司名称",
    )
    parser.add_argument(
        "--region",
        required=True,
        help="区域或机房描述",
    )
    parser.add_argument(
        "--description",
        default="自动扫描生成的网络拓扑",
        help="拓扑描述",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    snapshots = load_device_snapshots(input_dir)
    topology = build_topology(snapshots, args.company, args.region, args.description)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(topology, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
