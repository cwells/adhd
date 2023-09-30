"""
[bold cyan]Configure Python virtual environment.[/]

If [cyan]virtualenv[/] package is missing, plugin will still work with an existing
virtual environment, but won't be able to create a new one.
"""

example = """
python:
  venv: ~/myproject/.venv
  requirements: ~/myproject/requirements.txt
  packages: [ requests, PyYAML==5.4.1 ]
"""

required_modules: dict[str, str] = {"virtualenv": "virtualenv"}
required_binaries: list[str] = []

import os
import sys
from pathlib import Path

from lib.boot import missing_modules
from lib.shell import shell
from lib.util import ConfigBox, Style, console, get_resolved_path
from plugins import BasePlugin, MetadataType

if missing_modules(required_modules):
    console.print(f"{Style.WARNING}virtualenv module not found:[/] Python venv creation disabled.")
    virtualenv = None
else:
    import virtualenv


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "python"
    enabled: bool = True
    has_run: bool = False

    def load(self, config: ConfigBox, env: dict[str, str]) -> MetadataType:
        "Activate Python virtualenv."

        requirements: Path | None = None

        if _venv := config.get("venv"):
            venv: Path = get_resolved_path(_venv, env=env)
            if _req := config.get("requirements"):
                requirements = get_resolved_path(_req, env=env)
            packages: list[str] | None = config.get("packages")

            env.pop("PYTHONHOME", None)

            env.update(
                self.initialize_venv(
                    venv=venv.expanduser().resolve(),
                    requirements=requirements,
                    packages=packages,
                    env=env,
                )
            )
        else:
            env.pop("VIRTUAL_ENV", None)

        self.metadata["env"].update(env)

        return self.metadata

    def initialize_venv(
        self, venv: Path, requirements: Path | None, packages: list[str] | None, env: dict[str, str]
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
            if not self.silent:
                console.print(f"{Style.FINISHED}building Python virtual environment [yellow]{venv}[/]")

        if requirements:
            with console.status(
                f"[bold green]:white_circle:[/]Installing requirements from [yellow]{requirements}[/]"
            ):
                installed: bool = self.install_requirements(venv, requirements, env)
                if not self.silent:
                    style: Style = (Style.SKIPPED, Style.FINISHED)[installed]
                    console.print(f"{style}installing Python requirements from [yellow]{requirements}[/]")

        if packages:
            with console.status(f"[bold green]:white_circle:[/]Installing additional packages"):
                self.install_packages(venv, packages, env)
            if not self.silent:
                console.print(f"{Style.FINISHED}installing Python packages")

        return env

    def install_packages(self, venv: Path, packages: list[str], venv_env: dict[str, str]) -> int:
        "Install additional packages."

        bin_dir: Path = venv / "bin"
        python: Path = bin_dir / "python"
        packages_str: str = " ".join(packages)

        return shell(
            f"{python} -m pip install {packages_str} --upgrade",
            workdir=venv,
            env=venv_env,
        ).returncode

    def install_requirements(self, venv: Path, requirements: Path, venv_env: dict[str, str]) -> bool:
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
