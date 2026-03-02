from __future__ import annotations

from iotmd.collectors import DeviceSnapshot
from iotmd.collectors.common import collect_device_snapshot


COMMANDS = {
    "disable_paging": "screen-length 0 temporary",
    "config": "display current-configuration",
    "lldp": "display lldp neighbor brief",
    "interfaces": "display interface brief",
    "version": "display version",
}


# 函数说明: collect_huawei 的核心用途见函数实现逻辑。
def collect_huawei(
    name: str,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: int = 15,
) -> DeviceSnapshot:
    """采集华为设备配置、邻居、接口和版本信息。"""
    return collect_device_snapshot(
        name=name,
        vendor="huawei",
        host=host,
        port=port,
        username=username,
        password=password,
        disable_paging=COMMANDS["disable_paging"],
        config_cmd=COMMANDS["config"],
        lldp_cmd=COMMANDS["lldp"],
        interfaces_cmd=COMMANDS["interfaces"],
        version_cmd=COMMANDS["version"],
        timeout=timeout,
    )
