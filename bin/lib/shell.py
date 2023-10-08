import subprocess
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

from .util import ConfigBox

# ==============================================================================


def shell(
    command: str | Path,
    workdir: Path | None = None,
    env: ConfigBox | None = None,
    capture: bool = False,
    interactive: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    "Executes command in subshell and return CompletedProcess object."

    if workdir:
        workdir = workdir.expanduser().resolve()

    result: subprocess.CompletedProcess[bytes]

    if env is None:
        env = ConfigBox()

    try:
        result = subprocess.run(
            args=command,
            shell=True,
            cwd=workdir if workdir and workdir.exists() else None,
            env={k: str(v) for k, v in env.items()},
            capture_output=capture,
            stdout=subprocess.DEVNULL if not (interactive or capture) else None,
            stderr=subprocess.DEVNULL if not (interactive or capture) else None,
        )
    except Exception as e:
        raise RuntimeError(f"Error executing [yellow]{command}[/]: {e}", getattr(e, "errno", 1))

    return result


# ==============================================================================


def source(command: str | Path, env: ConfigBox, workdir: Path) -> dict:
    "Source a shell script and import its environment."

    _env: dict[str, str | None] = {}
    process: subprocess.CompletedProcess | None = None

    process = shell(f"source {command} && env", workdir=workdir, env=env, capture=True)

    if isinstance(process.stdout, bytes):
        _env = dotenv_values(stream=StringIO(process.stdout.decode()))

    return _env
