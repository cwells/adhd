import sys
import traceback
from collections.abc import MutableMapping
from enum import Enum
from pathlib import Path
from typing import Any

import click
import rich.console
import yaml
from box import Box
from toposort import CircularDependencyError, toposort_flatten

from lib.loader import get_loader

console: rich.console.Console = rich.console.Console()


# ==============================================================================


class Style(Enum):
    RUN = "[green]:black_circle:Run[/]"
    SKIP = "[yellow]:white_circle:Skip[/]"
    STARTING = "[green]:white_circle:Starting[/] "
    FINISHED = "[bold green]:black_circle:Finished[/] "
    SKIPPED = "[bold yellow]:white_circle:Skipped[/] "
    ERROR = "[red]:black_circle:Error[/] "
    WARNING = "[bold orange]:black_circle:Warning[/] "
    INFO = "[bold blue]:black_circle:[/] "
    TASK_RUN = "  [white]:arrow_right_hook:  "
    TASK_SKIP = "  [white]:arrow_right_hook:[grey50]  "
    TASK_FINISHED = "  [white]:arrow_right_hook:[/]  [green]Finished "
    START_LOAD = "[bold green]:white_circle:[/]loading "
    FINISH_LOAD = "[bold green]:black_circle:[/]loaded "

    def __str__(self):
        return self.value


# ==============================================================================


class ConfigBox(Box):
    "Preconfigured Box."

    def __init__(self, *args, **kwargs):
        kwargs["box_dots"] = True
        super().__init__(*args, **kwargs)


# ==============================================================================


class ProjectParamType(click.ParamType):
    """
    Click validator that accepts a project name,
    and returns absolute path to configuration.
    """

    name: str = "project"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> Path:
        home: Path = get_program_home()
        config: Path = home / "projects" / f"{value}.yaml"

        # fmt: off
        if not check_permissions(
            {
                config:            "0600",
                home:              "0700",
                home / "projects": "0700",
                home / "bin":      "0700",
                home / "bin/adhd": "0700",
            }
        ):
            sys.exit(1)
        # fmt: on

        if not config.is_file():
            self.fail(f"{value} is not a valid project.", param, ctx)

        return config


class EnvParamType(click.ParamType):
    "Click validator that accepts a string `X:v` and returns a tuple `('X', v)`"

    name: str = "env"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> tuple[Any, ...]:
        return tuple(v.strip() for v in value.split(":", 1))


class PluginParamType(click.ParamType):
    "Click validator that accepts a string `X:v` and returns a tuple['X', bool[v=='on']]`"

    name: str = "plugin"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> tuple[Any, ...]:
        value = tuple(v.strip() for v in value.split(":", 1))
        return (value[0], value[1] == "on")


# ==============================================================================


def _exit(msg: str, returncode: int = 1):
    "Print traceback to console, then exit program with returncode."

    console.print(f"{Style.ERROR}{msg}")
    exc = sys.exception()  # type: ignore
    console.print("".join(traceback.format_exception(exc)))
    sys.exit(returncode)


# ==============================================================================


def resolve_dependencies(env: dict[str, Any], workdir: Path) -> dict[str, Any]:
    deps: dict[str, set] = {k: set() for k in env}

    # build dependency tree
    for k, v in env.items():
        deps[k] = getattr(v, "dependencies", set())

    # resolve dependencies and reify LazyValues
    try:
        for k in toposort_flatten(deps):
            if _v := env.get(k):
                if callable(_v):
                    env[k] = str(_v(env=env, workdir=workdir))
                else:
                    env[k] = str(_v)
    except CircularDependencyError as e:
        return _exit(f"[red]Error: {e}[/]")

    return env


# ==============================================================================


def get_sorted_deps(command: str, commands: dict, workdir: Path, env: dict[str, Any]) -> list[str]:
    """
    Build a dependency tree of jobs that require other jobs,
    and return a flattened list of job execution order.
    """

    def get_deps(cmd: str) -> dict[str, list]:
        deps: dict[str, list] = {cmd: []}

        if _deps := commands.get(cmd, {}).get("after"):
            # if (skip := commands[cmd].get("skip")) and skip(env=env, workdir=workdir) == 0:
            #     _depstr: str = ", ".join([str(i) for i in (_deps if isinstance(_deps, list) else [_deps])])
            #     console.print(f"Skipping dependencies for {cmd} -> {_depstr}")
            #     # don't process this commands deps
            #     return deps

            deps[cmd] = [_deps] if isinstance(_deps, str) else _deps
            for _d in deps[cmd]:
                try:
                    deps.update(get_deps(_d))
                except RecursionError:
                    break  # will raise CircularDependencyError on return
        return deps

    try:
        return toposort_flatten(get_deps(command))
    except CircularDependencyError as e:
        return _exit(f"[red]Error: {e}[/]")


# ==============================================================================


def check_permissions(paths: dict[Path, str]) -> bool:
    "Validate permissions on program directories and files."

    def perm(p: Path) -> str:
        "Return a string with the octal representation of Unix file permissions."
        return oct(p.stat().st_mode)[-4:]

    insecure: list[str] = [
        f"- chmod {required} {p}" for p, required in paths.items() if not (actual := perm(p)) == required
    ]

    if insecure:
        console.print(f"\nInsecure configuration. Please run the following commands:\n")
        for issue in insecure:
            console.print(issue)
        console.print()

    return not insecure


# ==============================================================================


def nested_update(dst: ConfigBox, src: ConfigBox) -> ConfigBox:
    "Deep merge two nested dictionaries."

    for key in src.keys():
        if key in dst and isinstance(dst[key], MutableMapping) and isinstance(src[key], MutableMapping):
            nested_update(dst=dst[key], src=src[key])
        else:
            dst[key] = src[key]

    return dst


# ==============================================================================


def read_project_config(project: str) -> dict[str, Any]:
    with open(project) as config_file:
        return ConfigBox(yaml.load(config_file, Loader=get_loader()))


# ==============================================================================


def get_local_env(project_config: dict[str, Any], vars: dict[str, str]) -> dict[str, str]:
    """
    Get env from config (yaml source), then override with any preset local env vars.
    Env vars are resolved based on dependency resolution. A variable that depends on
    another variable will be reified _after_ its dependencies.
    """

    env: dict[str, str] = ConfigBox()
    workdir: Path = Path(project_config.get("home", "."))
    venv: Path | None
    # deps: dict[str, set] = {k: set() for k in project_config["env"]}

    if "env" not in project_config:
        project_config["env"] = ConfigBox()

    env = resolve_dependencies(project_config["env"], workdir)

    return env


# ==============================================================================


def get_program_home():
    bin_name: str = Path(sys.argv[0]).name
    config_dir: Path = Path(f"~/.{bin_name}").expanduser().resolve()

    return config_dir
