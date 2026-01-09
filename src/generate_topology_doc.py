#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_summary import generate_ai_summary

def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在：{path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def format_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["_无数据_"]
    header = "| " + " | ".join(columns) + " |"
    separator = "|" + "|".join([" --- " for _ in columns]) + "|"
    lines = [header, separator]
    for row in rows:
        values = [str(row.get(column, "")) for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def render_markdown(
    payload: dict[str, Any],
    ai_summary: str | None = None,
) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    company = payload.get("company", "未命名企业")
    region = payload.get("region", "未指定区域")
    description = payload.get("description", "无")
    topology = payload.get("topology", {})
    devices = payload.get("devices", [])

    lines = [
        f"# {company} 网络拓扑文档",
        "",
        f"- 生成时间：{now}",
        f"- 区域：{region}",
        f"- 说明：{description}",
        "",
        "## 拓扑概览",
    ]

    if ai_summary:
        lines.extend(
            [
                "",
                "## AI 自动生成摘要",
                ai_summary,
            ]
        )

    links = topology.get("links", [])
    if links:
        lines.append("| 起点 | 终点 | 介质 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for link in links:
            lines.append(
                "| {source} | {target} | {medium} | {note} |".format(
                    source=link.get("source", ""),
                    target=link.get("target", ""),
                    medium=link.get("medium", ""),
                    note=link.get("note", ""),
                )
            )
    else:
        lines.append("_无拓扑链接数据_")

    lines.append("")
    lines.append("## 设备清单")
    lines.extend(
        format_table(
            devices,
            ["name", "vendor", "model", "role", "management_ip"],
        )
    )

    lines.append("")
    lines.append("## 设备详情")
    if not devices:
        lines.append("_无设备详情_")
        return "\n".join(lines)

    for device in devices:
        lines.extend(
            [
                "",
                f"### {device.get('name', '未命名设备')}",
                f"- 厂商：{device.get('vendor', '')}",
                f"- 型号：{device.get('model', '')}",
                f"- 角色：{device.get('role', '')}",
                f"- 管理 IP：{device.get('management_ip', '')}",
            ]
        )

        interfaces = device.get("interfaces", [])
        lines.append("")
        lines.append("**接口信息**")
        lines.extend(format_table(interfaces, ["name", "status", "vlan", "description"]))

        configs = device.get("config_snippet", [])
        lines.append("")
        lines.append("**关键配置片段**")
        if configs:
            lines.append("```text")
            lines.extend([str(line) for line in configs])
            lines.append("```")
        else:
            lines.append("_无配置片段_")

    return "\n".join(lines)


def write_output(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据采集的拓扑与配置数据生成 Markdown 网络拓扑文档"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="输入 JSON 文件路径",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="输出 Markdown 文件路径",
    )
    parser.add_argument(
        "--ai-summary",
        action="store_true",
        help="启用 AI 自动生成摘要",
    )
    parser.add_argument(
        "--ai-endpoint",
        default="",
        help="AI 接口地址（OpenAI 兼容，留空则读取 AI_ENDPOINT）",
    )
    parser.add_argument(
        "--ai-model",
        default="",
        help="AI 模型名称（留空则读取 AI_MODEL）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    print(f"[IotMd] 读取输入文件: {input_path}")
    try:
        payload = load_json(input_path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    ai_summary = None
    if args.ai_summary:
        print("[IotMd] 正在生成 AI 摘要...")
        ai_summary = generate_ai_summary(payload, args.ai_endpoint, args.ai_model)
    content = render_markdown(payload, ai_summary)
    write_output(content, output_path)
    print(f"[IotMd] 已生成文档: {output_path}")


if __name__ == "__main__":
    main()
