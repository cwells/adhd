"""
Configure Python virtual environment.

This plugin will create a virtual environment and install requirements.txt. It also configures the proper environment variables so that you can enter the virtual environment just by spawning a shell, e.g. "adhd example /bin/bash". You can also specify packages to be installed via the [cyan]packages[/] attribute.

This plugin will also check the timestamp of your project's "requirements.txt" and if it detects a newer version, will reinstall project requirements.

The optional [cyan]exe[/] attribute allows you to specify which python binary to use when building the virtualenv. This allows use with tools like [cyan]asdf[/] and [cyan]pyenv[/].

Note that you [bold]must[/] manage your Python installations using external tools such as [cyan]asdf[/]. This plugin does not install Python.
"""

example = """
plugins:
  python:
    autoload: true
    venv: ~/myproject/.venv
    exe: ~/.asdf/installs/python/3.10.13/bin/python
    requirements: [ requirements.txt, dev-requirements.txt ]
    packages: [ requests, PyYAML==5.4.1 ]

# If you need to manage multiple Python versions for
# the same project, you can use something like this:

define:
- &asdf ~/.asdf/installs/python
- &python "3.10.13"
- &venv ~/.venv/myproject

plugins:
  python:
    venv: !path [ *venv, *python ]
    exe: !path [ *asdf, *python, bin/python ]

# The virtualenv will be created at ~/.venv/myproject/3.10.13.
"""

required_modules: dict[str, str] = {}
required_binaries: list[str] = []

import os
import sys
from pathlib import Path

import shutil
from lib.shell import shell
from lib.util import ConfigBox, Style, console, get_resolved_path
from plugins import BasePlugin, MetadataType


# ==============================================================================


class Plugin(BasePlugin):
    "Configure Python virtual environment."

    key: str = "python"
    enabled: bool = True
    exe: Path | None = None

    def load(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Activate Python virtualenv."

        requirements: list[Path] = []
        exe: Path | None = None

        if _exe := config.get("exe"):
            exe = get_resolved_path(str(_exe), env=env)
        else:
            if _exe := shutil.which("python"):
                exe = Path(_exe)

        if not (exe and exe.exists()):
            console.print(f"{Style.ERROR} Could not find Python executable.")
            sys.exit(2)

        self.exe = exe

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
            with console.status(f"Building virtual environment"):
                shell(f"{self.exe} -m venv {venv}", workdir=venv, env=env, interactive=True)
            self.print(f"building virtual environment [yellow]{venv}[/]", Style.PLUGIN_METHOD_SUCCESS)

        else:
            if not self.silent or self.verbose:
                self.print(f"building virtual environment [yellow]{venv}[/]", Style.PLUGIN_METHOD_SKIPPED)

        self.exe = bin_dir / "python"

        if requirements:
            with console.status(f"Installing requirements") as status:
                for _req in requirements:
                    status.update(f"Installing requirements [yellow]{_req}[/]")
                    installed: bool = self.install_requirements(venv, _req, env)
                    if not self.silent or installed or self.verbose or self.debug:
                        style: Style = (Style.PLUGIN_METHOD_SKIPPED, Style.PLUGIN_METHOD_SUCCESS)[installed]
                        self.print(f"installing requirements [yellow]{_req}[/]", style)

        if packages:
            with console.status(f"Installing additional packages"):
                self.install_packages(venv, packages, env)
            if not self.silent or self.verbose or self.debug:
                self.print("installing packages", Style.PLUGIN_METHOD_SUCCESS)

        return env

    def install_packages(self, venv: Path, packages: list[str], venv_env: ConfigBox) -> int:
        "Install additional packages."

        packages_str: str = " ".join(packages)

        return shell(
            f"{self.exe} -m pip install {packages_str} --upgrade",
            workdir=venv,
            env=venv_env,
        ).returncode

    def install_requirements(self, venv: Path, requirements: Path, venv_env: ConfigBox) -> bool:
        "Install requirements.txt into virtual env."

        pip_log: Path = venv / f"{requirements.name}.log"

        if not pip_log.exists() or (requirements.stat().st_mtime > pip_log.stat().st_mtime):
            shell(
                f"{self.exe} -m pip install -r {requirements} --upgrade > {pip_log}.tmp && mv {pip_log}.tmp {pip_log}",
                workdir=venv,
                env=venv_env,
            )
            return True

        return False
