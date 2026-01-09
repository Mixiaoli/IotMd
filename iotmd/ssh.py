from __future__ import annotations

import time
from dataclasses import dataclass

import paramiko


@dataclass(frozen=True)
class CommandResult:
    command: str
    output: str


def run_commands(
    host: str,
    port: int,
    username: str,
    password: str,
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
    )

    results: list[CommandResult] = []
    try:
        with client.invoke_shell() as shell:
            shell.settimeout(timeout)
            time.sleep(0.5)
            _drain(shell)

            for command in commands:
                shell.send(f"{command}\n")
                time.sleep(0.5)
                output = _read_until_prompt(shell)
                results.append(CommandResult(command=command, output=output))
    finally:
        client.close()

    return results


def _drain(shell: paramiko.Channel) -> None:
    while shell.recv_ready():
        shell.recv(65535)


def _read_until_prompt(shell: paramiko.Channel, pause: float = 0.3) -> str:
    buffer = []
    time.sleep(pause)
    while shell.recv_ready():
        buffer.append(shell.recv(65535).decode("utf-8", errors="ignore"))
        time.sleep(pause)
    return "".join(buffer)
