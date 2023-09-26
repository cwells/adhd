import sys
import traceback
from collections.abc import MutableMapping
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import click
import rich.console
from box import Box
from toposort import CircularDependencyError, toposort_flatten

console: rich.console.Console = rich.console.Console()


# ==============================================================================


class LazyValue:
    """
    Object that proxies a value in the form of a function and its arguments,
    as well as a list of any dependencies on other values this value may have.
    Specifically, this is used with toposort to linearly resolve inter-variable
    references during reification.

    For example, given the variable reference `FOO: !env ${BAR} ${BAZ}`, `FOO` will
    have the dependencies `["BAR", "BAZ"]`, and during reification, `BAZ` and `BAR`
    are guaranteed to be evaluated before `FOO`, thereby ensuring the value of `FOO`
    can be calculated without the need for recursion.
    """

    def __init__(self, fn: Callable, value: Any, deps: set[str]) -> None:
        self.__fn: Callable = fn
        self.__value: Any = value
        self.__deps: set[str] = deps

    def __call__(self, *args, **kwargs: Any) -> str:
        "Reify this value."

        return self.__fn(self, self.__value, *args, **kwargs)

    @property
    def dependencies(self) -> set[str]:
        "Return the list of dependencies."

        return self.__deps

    @property
    def value(self) -> Any:
        return self.__value


# ==============================================================================


class Style(Enum):
    RUN = "[green]:black_circle:Run[/]"
    SKIP = "[yellow]:white_circle:Skip[/]"
    STARTING = "[green]:white_circle:Starting[/] "
    FINISHED = "[bold green]:black_circle:Finished[/] "
    SKIPPED = "[bold yellow]:white_circle:Skipped[/] "
    ERROR = "[red]:black_circle:Error[/] "
    WARNING = "[bold orange4]:black_circle:Warning[/] "
    INFO = "[bold blue]:black_circle:[/] "
    TASK_RUN = "  [white]:arrow_right_hook:  "
    TASK_SKIP = "  [white]:arrow_right_hook:[grey50]  "
    TASK_FINISHED = "  [white]:arrow_right_hook:[/]  [green]Finished "
    START_LOAD = "[bold green]:white_circle:[/]Loading "
    FINISH_LOAD = "[bold green]:black_circle:[/]Loaded "
    SKIP_LOAD = "[bold yellow]:white_circle:[/]Skipped "
    OPEN_FINISHED = "  [white]:arrow_right_hook:[/]  [green]Opened "

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
        program: Path = Path(sys.argv[0])
        home: Path = get_project_home()
        config: Path = home / "projects" / f"{value}.yaml"

        # fmt: off
        if not check_permissions(
            {
                config:            "0600",
                home:              "0700",
                home / "projects": "0700",
                program.parent:    "0700", # bin/
                program:           "0700", # bin/adhd
            }
        ): sys.exit(1)
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


def _exit(exc: Exception, returncode: int = 1, verbose: bool = False, debug: bool = False) -> None:
    "Print traceback to console, then exit program with returncode."

    console.print(exc)

    if debug:
        console.print("\n")
        console.print("".join(traceback.format_exception(exc)))
        console.print()

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
        _exit(e)

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
        _exit(e)

    return []  # never gets here, but makes mypy happy


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


def get_local_env(project_config: dict[str, Any], vars: dict[str, str]) -> dict[str, str]:
    """
    Get env from config (yaml source), then override with any preset local env vars.
    Env vars are resolved based on dependency resolution. A variable that depends on
    another variable will be reified _after_ its dependencies.
    """

    home: str | LazyValue = project_config.get("home", ".")
    env: dict[str, str] = ConfigBox()
    workdir: Path = get_resolved_path(home, env=project_config["env"])

    if "env" not in project_config:
        project_config["env"] = ConfigBox()

    env = resolve_dependencies(project_config["env"], workdir)

    return env


# ==============================================================================


def get_program_bin() -> Path:
    program: Path = Path(sys.argv[0]).resolve()
    console.print(program.parent)
    return program.parent


def get_project_home() -> Path:
    program: Path = Path(sys.argv[0])
    config_dir: Path = Path(f"~/.{program.name}").expanduser().resolve()

    return config_dir


# ==============================================================================


def print_job_help(jobs: dict) -> None:
    _width = max(len(j) for j in jobs) + 22
    console.print()
    for job, config in jobs.items():
        console.print(f" :white_circle:{f'[bold cyan]{job}[/] [dim]':.<{_width}}[/] {config.get('help', '')}")
    console.print()


# ==============================================================================


def get_resolved_path(path: str | LazyValue, env: dict, workdir: Path | None = None) -> Path:
    "Resolves string or LazyValue into fully-qualified path."

    workdir = Path(".") if not workdir else workdir
    _path: Path = Path(path(env=env, workdir=workdir) if isinstance(path, LazyValue) else path)
    _path = _path.expanduser().resolve()
    return _path
