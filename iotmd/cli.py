from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass
class CollectError:
    device_name: str
    message: str


Collector = Callable[[dict[str, Any]], Any]


def collect_snapshots_safe(inventory: Iterable[dict[str, Any]], collector: Collector) -> tuple[list[Any], list[CollectError]]:
    """Collect snapshots without raising for per-device failures.

    Returns successful snapshots and per-device errors.
    """
    snapshots: list[Any] = []
    errors: list[CollectError] = []

    for device in inventory:
        name = str(device.get("name") or device.get("host") or "unknown-device")
        try:
            snapshots.append(collector(device))
        except Exception as exc:  # noqa: BLE001 - interactive CLI should continue
            errors.append(CollectError(device_name=name, message=str(exc)))

    return snapshots, errors


def generate_chat_reply(question: str, snapshots: list[Any] | None = None) -> str:
    """Generate a chat reply even if no snapshots have been collected."""
    text = question.strip()
    if not text:
        return "请先输入一个问题。"

    if not snapshots:
        return (
            "我可以先和你正常聊天。\n"
            "如果你希望我回答设备相关问题，可以稍后输入“加载设备”重新采集交换机信息。"
        )

    return "已收到问题，我会结合已采集的设备信息继续回答。"


def prompt_retry_after_collect_error(errors: list[CollectError]) -> str:
    if not errors:
        return ""
    details = "\n".join(f"- {item.device_name}: {item.message}" for item in errors)
    return (
        "以下设备采集失败，但不会中断对话：\n"
        f"{details}\n"
        "你可以继续聊天，或输入“加载设备”后重新采集。"
    )
