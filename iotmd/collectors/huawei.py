from __future__ import annotations

from iotmd.collectors import DeviceSnapshot
from iotmd.ssh import run_commands


COMMANDS = {
    "config": "display current-configuration",
    "lldp": "display lldp neighbor",
    "interfaces": "display interface brief",
}


def collect_huawei(
    name: str,
    host: str,
    port: int,
    username: str,
    password: str,
) -> DeviceSnapshot:
    results = run_commands(
        host=host,
        port=port,
        username=username,
        password=password,
        commands=list(COMMANDS.values()),
    )

    outputs = {item.command: item.output for item in results}
    return DeviceSnapshot(
        name=name,
        vendor="huawei",
        config=outputs.get(COMMANDS["config"], ""),
        lldp=outputs.get(COMMANDS["lldp"], ""),
        interfaces=outputs.get(COMMANDS["interfaces"], ""),
    )
