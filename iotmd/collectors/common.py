from __future__ import annotations

from iotmd.collectors import DeviceSnapshot
from iotmd.ssh import run_commands


# 函数说明: collect_device_snapshot 的核心用途见函数实现逻辑。
def collect_device_snapshot(
    *,
    name: str,
    vendor: str,
    host: str,
    port: int,
    username: str,
    password: str,
    disable_paging: str,
    config_cmd: str,
    lldp_cmd: str,
    interfaces_cmd: str,
    version_cmd: str,
    timeout: int = 15,
) -> DeviceSnapshot:
    """统一采集设备核心信息并封装为快照对象。"""
    command_map = {
        "config": config_cmd,
        "lldp": lldp_cmd,
        "interfaces": interfaces_cmd,
        "version": version_cmd,
    }
    results = run_commands(
        host=host,
        port=port,
        username=username,
        password=password,
        pre_commands=[disable_paging],
        commands=list(command_map.values()),
        timeout=timeout,
    )

    outputs = {item.command: item.output for item in results}
    return DeviceSnapshot(
        name=name,
        vendor=vendor,
        config=outputs.get(command_map["config"], ""),
        lldp=outputs.get(command_map["lldp"], ""),
        interfaces=outputs.get(command_map["interfaces"], ""),
        version=outputs.get(command_map["version"], ""),
    )
