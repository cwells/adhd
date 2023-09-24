import subprocess
from pathlib import Path


# ==============================================================================


def shell(
    command: str,
    workdir: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
    interactive: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    "Executes command in subshell and return CompletedProcess object."

    if workdir:
        workdir = workdir.expanduser().resolve()

    result: subprocess.CompletedProcess[bytes]
    if env is not None:
        env = {k: str(v) for k, v in env.items()}
    try:
        result = subprocess.run(
            args=command,
            shell=True,
            cwd=workdir if workdir and workdir.exists() else None,
            env=env or {},
            capture_output=capture and not interactive,
            stdout=subprocess.DEVNULL if not (interactive or capture) else None,
            stderr=subprocess.DEVNULL if not (interactive or capture) else None,
        )
    except Exception as e:
        raise RuntimeError(f"Error executing [yellow]{command}[/]: {e}", getattr(e, "errno", 1))

    return result
