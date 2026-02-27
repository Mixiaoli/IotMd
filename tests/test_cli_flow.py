from iotmd.cli import collect_snapshots_safe, generate_chat_reply, prompt_retry_after_collect_error


def test_chat_works_without_snapshots():
    reply = generate_chat_reply("你好", snapshots=[])
    assert "正常聊天" in reply
    assert "重新采集" in reply


def test_collect_error_does_not_raise_and_can_continue():
    devices = [{"name": "sw1"}, {"name": "sw2"}]

    def fake_collector(device):
        if device["name"] == "sw1":
            raise ConnectionError("Unable to connect")
        return {"ok": device["name"]}

    snapshots, errors = collect_snapshots_safe(devices, fake_collector)

    assert snapshots == [{"ok": "sw2"}]
    assert len(errors) == 1

    message = prompt_retry_after_collect_error(errors)
    assert "不会中断对话" in message
    assert "重新采集" in message
