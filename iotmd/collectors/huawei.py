from __future__ import annotations

from iotmd.collectors import DeviceSnapshot
from iotmd.ssh import run_commands


COMMANDS = {
    "disable_paging": "screen-length 0 temporary",
    "config": "display current-configuration",
    "lldp": "display lldp neighbor brief",
    "interfaces": "display interface brief",
    "version": "display version",
}


def collect_huawei(
    name: str,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: int = 15,
) -> DeviceSnapshot:
    results = run_commands(
        host=host,
        port=port,
        username=username,
        password=password,
        pre_commands=[COMMANDS["disable_paging"]],
        commands=[
            COMMANDS["config"],
            COMMANDS["lldp"],
            COMMANDS["interfaces"],
            COMMANDS["version"],
        ],
        timeout=timeout,
    )

    outputs = {item.command: item.output for item in results}
    return DeviceSnapshot(
        name=name,
        vendor="huawei",
        config=outputs.get(COMMANDS["config"], ""),
        lldp=outputs.get(COMMANDS["lldp"], ""),
        interfaces=outputs.get(COMMANDS["interfaces"], ""),
        version=outputs.get(COMMANDS["version"], ""),
    )
