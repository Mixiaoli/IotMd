from __future__ import annotations

import ipaddress
import platform
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from iotmd.config import SubnetHost


def scan_subnet(cidr: str, ssh_port: int = 22, ping_workers: int = 128, timeout: float = 0.8) -> list[SubnetHost]:
    hosts = [str(ip) for ip in ipaddress.ip_network(cidr, strict=False).hosts()]
    online_map: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=ping_workers) as executor:
        futures = {executor.submit(_ping_host, host, timeout): host for host in hosts}
        for future in as_completed(futures):
            online_map[futures[future]] = future.result()

    results: list[SubnetHost] = []
    for host in sorted(hosts, key=lambda ip: tuple(int(part) for part in ip.split("."))):
        online = online_map.get(host, False)
        if not online:
            results.append(SubnetHost(host=host, online=False, ssh_open=False, remark="预留（Ping 不通）"))
            continue
        ssh_open = _is_port_open(host, ssh_port, timeout)
        remark = "" if ssh_open else f"Ping 通，端口 {ssh_port} 不可达"
        results.append(SubnetHost(host=host, online=True, ssh_open=ssh_open, remark=remark))
    return results


def _ping_host(host: str, timeout: float) -> bool:
    system = platform.system().lower()
    if system == "windows":
        timeout_ms = str(max(int(timeout * 1000), 200))
        command = ["ping", "-n", "1", "-w", timeout_ms, host]
    else:
        timeout_sec = str(max(int(round(timeout)), 1))
        command = ["ping", "-c", "1", "-W", timeout_sec, host]
    return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _is_port_open(host: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0
