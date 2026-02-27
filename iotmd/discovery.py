from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed


def discover_ssh_hosts(cidr: str, port: int = 22, timeout: float = 0.6, workers: int = 64) -> list[str]:
    """Discover reachable SSH hosts in a subnet."""
    network = ipaddress.ip_network(cidr, strict=False)
    candidates = [str(ip) for ip in network.hosts()]

    reachable: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_is_port_open, host, port, timeout): host for host in candidates
        }
        for future in as_completed(futures):
            if future.result():
                reachable.append(futures[future])

    return sorted(reachable, key=lambda ip: tuple(int(part) for part in ip.split(".")))


def _is_port_open(host: str, port: int, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0
