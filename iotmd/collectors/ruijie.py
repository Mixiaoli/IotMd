from __future__ import annotations

from iotmd.collectors import DeviceSnapshot
from iotmd.ssh import run_commands


COMMANDS = {
    "disable_paging": "terminal length 0",
    "config": "show running-config",
    "lldp": "show lldp neighbors",
    "interfaces": "show interfaces brief",
}


def collect_ruijie(
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
        ],
        timeout=timeout,
    )

    outputs = {item.command: item.output for item in results}
    return DeviceSnapshot(
        name=name,
        vendor="ruijie",
        config=outputs.get(COMMANDS["config"], ""),
        lldp=outputs.get(COMMANDS["lldp"], ""),
        interfaces=outputs.get(COMMANDS["interfaces"], ""),
    )
