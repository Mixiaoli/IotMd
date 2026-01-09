#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from ai_client import call_ai


VENDOR_COMMANDS = {
    "huawei": [
        "display version",
        "display interface brief",
        "display lldp neighbor brief",
    ],
    "ruijie": [
        "show version",
        "show interface status",
        "show lldp neighbors",
    ],
}


def run_ssh_commands(host: str, username: str, ssh_key: str, commands: list[str]) -> dict[str, str]:
    results: dict[str, str] = {}
    for command in commands:
        ssh_command = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-i",
            ssh_key,
            f"{username}@{host}",
            command,
        ]
        output = subprocess.check_output(ssh_command, text=True, stderr=subprocess.STDOUT)
        results[command] = output.strip()
    return results


def build_base_snapshot(
    name: str,
    vendor: str,
    management_ip: str,
    raw_outputs: dict[str, str],
) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": vendor,
        "model": "",
        "role": "",
        "management_ip": management_ip,
        "interfaces": [],
        "config_snippet": [],
        "neighbors": [],
        "raw_outputs": raw_outputs,
    }


def parse_with_ai(
    payload: dict[str, Any],
    endpoint: str,
    model: str,
) -> dict[str, Any]:
    prompt = (
        "请把以下设备采集输出解析为标准化 JSON，字段包括："
        "name, vendor, model, role, management_ip, interfaces (name/status/vlan/description), "
        "neighbors (device/local_interface/remote_interface/medium/note), "
        "config_snippet (list), raw_outputs。"
        "如果无法确定字段，请留空字符串或空列表。\n"
        f"采集数据：{json.dumps(payload, ensure_ascii=False)}"
    )
    response, error = call_ai(
        prompt,
        endpoint=endpoint,
        model=model,
        system_prompt="你是网络设备数据解析助手。",
    )
    if error or not response:
        return payload
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return payload


def collect_interactive() -> dict[str, Any]:
    name = input("设备名称: ").strip()
    vendor = input("厂商 (huawei/ruijie): ").strip()
    model = input("型号: ").strip()
    role = input("角色: ").strip()
    management_ip = input("管理 IP: ").strip()
    interfaces: list[dict[str, Any]] = []
    while True:
        add_interface = input("添加接口信息? (y/n): ").strip().lower()
        if add_interface != "y":
            break
        interfaces.append(
            {
                "name": input("接口名称: ").strip(),
                "status": input("接口状态: ").strip(),
                "vlan": input("VLAN: ").strip(),
                "description": input("描述: ").strip(),
            }
        )
    neighbors: list[dict[str, Any]] = []
    while True:
        add_neighbor = input("添加邻居信息? (y/n): ").strip().lower()
        if add_neighbor != "y":
            break
        neighbors.append(
            {
                "device": input("邻居设备名称: ").strip(),
                "local_interface": input("本地接口: ").strip(),
                "remote_interface": input("对端接口: ").strip(),
                "medium": input("链路介质: ").strip(),
                "note": input("备注: ").strip(),
            }
        )
    config_snippet: list[str] = []
    while True:
        line = input("关键配置片段(空行结束): ")
        if not line:
            break
        config_snippet.append(line)
    return {
        "name": name,
        "vendor": vendor,
        "model": model,
        "role": role,
        "management_ip": management_ip,
        "interfaces": interfaces,
        "config_snippet": config_snippet,
        "neighbors": neighbors,
    }


def ai_interview(
    endpoint: str,
    model: str,
) -> dict[str, Any]:
    system_prompt = "你是网络设备采集助手，需要通过问答收集设备信息。"
    prompt = (
        "请输出一个问题列表(JSON 数组)，用于采集网络设备快照。"
        "每个问题包含字段 id, question, hint。必须覆盖：设备名称、厂商、型号、角色、管理IP、"
        "接口列表、邻居列表、关键配置片段。"
        "接口列表和邻居列表需要提示用户可多次输入，直到输入空行结束。"
    )
    response, error = call_ai(prompt, endpoint=endpoint, model=model, system_prompt=system_prompt)
    if error or not response:
        raise SystemExit(f"AI 交互失败：{error or '无返回内容'}")
    try:
        questions = json.loads(response)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"AI 交互失败：问题列表解析错误（{exc}）")

    answers: dict[str, Any] = {}
    for item in questions:
        question = item.get("question", "")
        hint = item.get("hint", "")
        if item.get("id") in {"interfaces", "neighbors", "config_snippet"}:
            print(f"{question} {hint}".strip())
            entries: list[Any] = []
            while True:
                line = input("> ").strip()
                if not line:
                    break
                entries.append(line)
            answers[item.get("id")] = entries
        else:
            prompt_text = f"{question} {hint}".strip() + ": "
            answers[item.get("id")] = input(prompt_text).strip()

    normalize_prompt = (
        "请将以下用户回答整理为标准化设备快照 JSON，字段包括："
        "name, vendor, model, role, management_ip, interfaces (name/status/vlan/description), "
        "neighbors (device/local_interface/remote_interface/medium/note), config_snippet (list)。"
        "如果字段缺失，请返回空字符串或空列表。\n"
        f"用户回答：{json.dumps(answers, ensure_ascii=False)}"
    )
    normalized, error = call_ai(
        normalize_prompt,
        endpoint=endpoint,
        model=model,
        system_prompt="你是网络设备数据整理助手。",
    )
    if error or not normalized:
        raise SystemExit(f"AI 交互失败：{error or '无返回内容'}")
    try:
        return json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"AI 交互失败：设备快照解析错误（{exc}）")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="采集设备信息生成快照 JSON")
    parser.add_argument("--output", required=True, help="输出 JSON 文件路径")
    parser.add_argument("--vendor", choices=sorted(VENDOR_COMMANDS.keys()), help="设备厂商")
    parser.add_argument("--host", help="设备管理 IP 或主机名")
    parser.add_argument("--username", help="SSH 用户名")
    parser.add_argument("--ssh-key", help="SSH 私钥路径（推荐使用密钥登录）")
    parser.add_argument("--name", default="", help="设备名称（缺省时使用 host）")
    parser.add_argument("--management-ip", default="", help="管理 IP（缺省时使用 host）")
    parser.add_argument("--ai-parse", action="store_true", help="使用 AI 解析采集输出")
    parser.add_argument("--ai-endpoint", default="", help="AI 接口地址")
    parser.add_argument("--ai-model", default="", help="AI 模型名称")
    parser.add_argument("--interactive", action="store_true", help="交互式手动录入")
    parser.add_argument("--ai-interactive", action="store_true", help="AI 引导式交互录入")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.interactive:
        snapshot = collect_interactive()
    elif args.ai_interactive:
        snapshot = ai_interview(args.ai_endpoint, args.ai_model)
    elif args.host and args.vendor and args.username and args.ssh_key:
        commands = VENDOR_COMMANDS[args.vendor]
        raw_outputs = run_ssh_commands(args.host, args.username, args.ssh_key, commands)
        snapshot = build_base_snapshot(
            name=args.name or args.host,
            vendor=args.vendor,
            management_ip=args.management_ip or args.host,
            raw_outputs=raw_outputs,
        )
        if args.ai_parse:
            snapshot = parse_with_ai(snapshot, args.ai_endpoint, args.ai_model)
    else:
        raise SystemExit(
            "请使用 --interactive 手动录入，或提供 --host/--vendor/--username/--ssh-key 进行自动采集。"
        )

    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
