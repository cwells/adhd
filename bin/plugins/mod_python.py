"""
Configure Python virtual environment.

This plugin will create a virtual environment and install requirements.txt. It also configures the proper environment variables so that you can enter the virtual environment just by spawning a shell, e.g. "adhd example /bin/bash". You can also specify packages to be installed via the [cyan]packages[/] attribute.

This plugin will also check the timestamp of your project's "requirements.txt" and if it detects a newer version, will reinstall project requirements.
"""

example = """
plugins:
  python:
    autoload: true
    venv: ~/myproject/.venv
    requirements: [ requirements.txt, dev-requirements.txt ]
    packages: [ requests, PyYAML==5.4.1 ]
"""

required_modules: dict[str, str] = {}
required_binaries: list[str] = []

import os
from pathlib import Path

from lib.shell import shell
from lib.util import ConfigBox, Style, console, get_resolved_path
from plugins import BasePlugin, MetadataType


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "python"
    enabled: bool = True
    has_run: bool = False

    def load(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Activate Python virtualenv."

        requirements: list[Path] = []

        if _venv := config.get("venv"):
            venv: Path = get_resolved_path(_venv, env=env)

            if _req := config.get("requirements"):
                if isinstance(_req, str):
                    _req = [_req]
                for _r in _req:
                    requirements.append(get_resolved_path(_r, env=env))
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
        self,
        venv: Path,
        requirements: list[Path] | None,
        packages: list[str] | None,
        env: ConfigBox,
    ) -> dict[str, str]:
        "Create the virtual environment if it doesn't exist, return env vars needed for venv."

        bin_dir: Path = venv / "bin"
        venv_env: ConfigBox = ConfigBox(
            {
                "VIRTUAL_ENV": str(venv),
                "PATH": os.pathsep.join([str(bin_dir), env["PATH"]]),
            }
        )
        style: Style

        env.update(venv_env)
        bin_dir.mkdir(parents=True, exist_ok=True)

        if not (bin_dir / "python").exists():
            with console.status(f"Building Python virtual environment"):
                shell(f"python -m venv {venv}", workdir=venv, env=env, interactive=True)
            self.print(f"{Style.FINISHED}building Python virtual environment [yellow]{venv}[/]")

        else:
            if not self.silent or self.verbose:
                self.print(f"{Style.SKIPPED}building Python virtual environment [yellow]{venv}[/]")

        if requirements:
            with console.status(f"Installing requirements") as status:
                for _req in requirements:
                    status.update(f"Installing requirements from [yellow]{_req}[/]")
                    installed: bool = self.install_requirements(venv, _req, env)
                    if not self.silent or self.verbose:
                        style = (Style.SKIP, Style.FINISHED)[installed]
                        self.print(f"{style}installing Python requirements from [yellow]{_req}[/]")

        if packages:
            with console.status(f"Installing additional packages"):
                self.install_packages(venv, packages, env)
            if not self.silent or self.verbose:
                self.print(f"{Style.FINISHED}installing Python packages")

        return env

    def install_packages(self, venv: Path, packages: list[str], venv_env: ConfigBox) -> int:
        "Install additional packages."

        bin_dir: Path = venv / "bin"
        python: Path = bin_dir / "python"
        packages_str: str = " ".join(packages)

        return shell(
            f"{python} -m pip install {packages_str} --upgrade",
            workdir=venv,
            env=venv_env,
        ).returncode

    def install_requirements(self, venv: Path, requirements: Path, venv_env: ConfigBox) -> bool:
        "Install requirements.txt into virtual env."

        bin_dir: Path = venv / "bin"
        python: Path = bin_dir / "python"
        pip_log: Path = venv / f"{requirements.name}.log"

        if not pip_log.exists() or (requirements.stat().st_mtime > pip_log.stat().st_mtime):
            shell(
                f"{python} -m pip install -r {requirements} --upgrade > {pip_log}",
                workdir=venv,
                env=venv_env,
            )
            return True

        return False
