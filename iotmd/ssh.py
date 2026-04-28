from __future__ import annotations

from typing import Optional
import logging
import time
from dataclasses import dataclass

import paramiko


logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)


@dataclass(frozen=True)
class CommandResult:
    command: str
    output: str


def run_commands(
    host: str,
    port: int,
    username: str,
    password: str,
    pre_commands: list[str],
    commands: list[str],
    timeout: int = 15,
) -> list[CommandResult]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )

    results: list[CommandResult] = []
    shell: Optional[paramiko.Channel] = None
    try:
        shell = client.invoke_shell(width=240, height=1000)
        shell.settimeout(timeout)
        time.sleep(0.8)
        _drain(shell)

        for command in pre_commands:
            shell.send(f"{command}\n")
            time.sleep(0.6)
            _drain(shell)

        for command in commands:
            shell.send(f"{command}\n")
            output = _read_until_stable(shell, timeout=timeout)
            results.append(CommandResult(command=command, output=output))
    finally:
        if shell is not None:
            try:
                shell.close()
            except Exception:
                pass
        client.close()

    return results


def _drain(shell: paramiko.Channel) -> None:
    while True:
        try:
            if not shell.recv_ready():
                return
            shell.recv(65535)
        except Exception:
            return


def _read_until_stable(
    shell: paramiko.Channel,
    pause: float = 0.35,
    timeout: int = 15,
) -> str:
    buffer: list[str] = []
    deadline = time.time() + timeout
    stable_rounds = 0

    while time.time() < deadline:
        time.sleep(pause)
        chunk_found = False
        while True:
            try:
                if not shell.recv_ready():
                    break
                data = shell.recv(65535)
            except Exception:
                return "".join(buffer)

            if not data:
                return "".join(buffer)
            chunk_found = True
            buffer.append(data.decode("utf-8", errors="ignore"))

        if chunk_found:
            stable_rounds = 0
        else:
            stable_rounds += 1

        if stable_rounds >= 2:
            break

    return "".join(buffer)
