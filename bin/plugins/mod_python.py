"""
[bold cyan]Configure Python virtual environment.[/]

  python:
    venv: ~/myproject/.venv                    # location venv will be created
    requirements: ~/myproject/requirements.txt # optional requirements.txt to be installed
    packages: [ requests, PyYAML==5.4.1 ]      # additional packages to install

If `virtualenv` package is missing, plugin will still work with an existing
virtual environment, but won't be able to create a new one.
"""

import os
import sys
from pathlib import Path

from lib.shell import shell
from lib.util import console, Style, ConfigBox, get_resolved_path
from lib.plugins import PluginTarget
from lib.boot import missing_modules


key: str | None = "python"
target: PluginTarget = PluginTarget.ENV
has_run: bool = False

if missing_modules(["virtualenv"]):
    console.print(f"{Style.WARNING}virtualenv module not found:[/] Python venv creation disabled.")
    virtualenv = None
else:
    import virtualenv


# ==============================================================================


def load(config: ConfigBox, env: dict[str, str]) -> dict[str, str]:
    "Activate Python virtualenv."

    requirements: Path | None = None

    if _venv := config.get("venv"):
        venv: Path = get_resolved_path(_venv, env=env)
        if _req := config.get("requirements"):
            requirements = get_resolved_path(_req, env=env)
        packages: list[str] | None = config.get("packages")

        env.pop("PYTHONHOME", None)

        env.update(
            initialize_venv(
                venv=venv.expanduser().resolve(),
                requirements=requirements,
                packages=packages,
                env=env,
            )
        )
    else:
        env.pop("VIRTUAL_ENV", None)

    return env


# ==============================================================================


def initialize_venv(
    venv: Path, requirements: Path | None, packages: list[str] | None, env: dict[str, str]
) -> dict[str, str]:
    "Create the virtual environment if it doesn't exist, return env vars needed for venv."

    bin_dir: Path = venv / "bin"
    venv_env: dict[str, str] = {
        "VIRTUAL_ENV": str(venv),
        "PATH": os.pathsep.join([str(bin_dir), env["PATH"]]),
    }

    env.update(venv_env)
    bin_dir.mkdir(parents=True, exist_ok=True)

    if not (bin_dir / "python").exists():
        if virtualenv is None:
            console.print(f"{Style.ERROR}Virtualenv creation is disabled. Please install virtualenv package.")
            sys.exit(1)

        with console.status(f"[bold green]:white_circle:[/]Building Python virtual environment"):
            virtualenv.cli_run(
                [str(venv)],
                options=None,
                setup_logging=True,
                env=env,
            )
        console.print(f"{Style.FINISHED}building Python virtual environment [yellow]{venv}[/]")

    if requirements:
        with console.status(
            f"[bold green]:white_circle:[/]Installing requirements from [yellow]{requirements}[/]"
        ):
            installed: bool = install_requirements(venv, requirements, env)
            style: Style = (Style.SKIPPED, Style.FINISHED)[installed]
            console.print(f"{style}installing Python requirements from [yellow]{requirements}[/]")

    if packages:
        with console.status(f"[bold green]:white_circle:[/]Installing additional packages"):
            install_packages(venv, packages, env)
        console.print(f"{Style.FINISHED}installing Python packages")

    return env


# ==============================================================================


def install_packages(venv: Path, packages: list[str], venv_env: dict[str, str]) -> int:
    "Install additional packages."

    bin_dir: Path = venv / "bin"
    python: Path = bin_dir / "python"
    packages_str: str = " ".join(packages)

    return shell(
        f"{python} -m pip install {packages_str} --upgrade",
        workdir=venv,
        env=venv_env,
    ).returncode


# ==============================================================================


def install_requirements(
    venv: Path,
    requirements: Path,
    venv_env: dict[str, str],
    verbose: bool = False,
) -> bool:
    "Install requirements.txt into virtual env."

    bin_dir: Path = venv / "bin"
    python: Path = bin_dir / "python"
    pip_log: Path = venv / "pip.log"

    if not pip_log.exists() or (requirements.stat().st_mtime > pip_log.stat().st_mtime):
        shell(
            f"{python} -m pip install -r {requirements} --upgrade > {pip_log}",
            workdir=venv,
            env=venv_env,
        )
        return True

    return False
