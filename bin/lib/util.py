import sys
import traceback
from collections.abc import MutableMapping
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import click
import rich.console
import rich.style
from box import Box
from rich.syntax import Syntax
from rich.table import Table
from toposort import CircularDependencyError, toposort_flatten

console: rich.console.Console = rich.console.Console(color_system="truecolor")


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

state_len: int = 9


class Style(Enum):
    JOB_UP = f"[bold green]:black_circle:[/]{'Finished':<{state_len}}"
    JOB_DOWN = f"[dim]:black_circle:[/]{'Stopped':<{state_len}}"
    JOB_RUN = f"[green]:black_circle:[/]{'Running':<{state_len}}"
    JOB_RUN_STATUS = f"{'Running':<{state_len}}"
    JOB_SKIP = f"[bold green]:white_circle:[/][dim]{'Skipped':<{state_len}}[/]"

    TASK_RUN = "  [white]:arrow_right_hook:[/]  "
    TASK_SKIP = "  [white]:arrow_right_hook:[dim white]  "
    TASK_FINISHED = "  [white]:arrow_right_hook:[/]  [green]Finished "

    PLUGIN_LOAD = f"[bold green]:electric_plug:[/]{'Load':<{state_len}}"
    PLUGIN_UNLOAD = f"[dim yellow]:electric_plug:[/]{'Unload':<{state_len}}"
    PLUGIN_INFO = "[bold cyan]:electric_plug:[/]"
    PLUGIN_SKIP = f"[dim]:electric_plug:[/]{'Skipped':<{state_len}}"
    PLUGIN_METHOD_SUCCESS = "[bold green]:arrow_right_hook:[/] Finished "
    PLUGIN_METHOD_SKIPPED = "[dim]:arrow_right_hook:[/] Skipped "
    PLUGIN_METHOD_FAILED = "[dim]:arrow_right_hook:[/][red] Failed "

    EXPLAIN_RUN = f"{'[bold green]:black_circle:[/]Would [bold green]run[/]':<{state_len}}"
    EXPLAIN_SKIP = f"{':white_circle:Would [bold yellow]skip[/]':<{state_len}}"

    OPEN_FINISHED = "  [white]:arrow_right_hook:[/]  [green]Opened "

    ERROR = "[red]:black_circle:Error[/] "
    WARNING = "[bold orange4]:black_circle:Warning[/] "
    INFO = "[bold blue]:black_circle:[/]"
    SUCCESS = "[bold green]Finished[/] "
    UP = "[bold green]:black_circle:[/]"
    DOWN = "[dim white]:black_circle:[/]"
    SKIP = "[dim white]:white_circle:[/]"

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
        home: Path = get_project_home()
        config: Path = home / "projects" / f"{value}.yaml"

        if not config.is_file():
            self.fail(f"{value} is not a valid project configuration {config}.", param, ctx)

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


def resolve_dependencies(env: ConfigBox, workdir: Path) -> ConfigBox:
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


def get_sorted_deps(command: str, commands: dict, workdir: Path, env: ConfigBox) -> list[str]:
    """
    Build a dependency tree of jobs that require other jobs,
    and return a flattened list of job execution order.
    """

    def get_deps(cmd: str) -> dict[str, list]:
        deps: dict[str, list] = {cmd: []}

        if _deps := commands.get(cmd, {}).get("after"):
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


def check_permissions(paths: dict[Path, int], fix_perms: bool = False) -> bool:
    "Validate permissions on program directories and files."

    def perm(p: Path) -> int | None:
        "Return POSIX file permissions."

        try:
            return p.stat().st_mode & 0o000777
        except Exception as e:
            _exit(e)

    # fmt: off
    insecure: list[tuple[Path, int]] = [
        (p, required)
        for p, required in paths.items()
        if not perm(p) == required
    ]
    # fmt: on

    if insecure:
        console.print(f"\nInsecure configuration:")

        for path, mode in insecure:
            if fix_perms:
                path.chmod(mode)
                console.print(f"- fixed {path} ({mode:04o})")
            else:
                print(mode, path)
                console.print(f"- chmod {mode:04o} {path}")

        console.print()

    return not insecure or fix_perms


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


def get_local_env(project_config: dict[str, Any], vars: dict[str, str]) -> ConfigBox:
    """
    Get env from config (yaml source), then override with any preset local env vars.
    Env vars are resolved based on dependency resolution. A variable that depends on
    another variable will be reified _after_ its dependencies.
    """

    home: str | LazyValue = project_config.get("home", ".")
    env: ConfigBox = ConfigBox()
    workdir: Path = get_resolved_path(home, env=project_config["env"])

    project_config.setdefault("env", ConfigBox())
    env = ConfigBox(resolve_dependencies(project_config["env"], workdir))

    return env


# ==============================================================================


def get_program_bin() -> Path:
    program: Path = Path(sys.argv[0]).resolve()
    return program.parent


def get_project_home() -> Path:
    program: Path = Path(sys.argv[0])
    config_dir: Path = Path(f"~/.{program.name}").expanduser().resolve()
    return config_dir


# ==============================================================================


def print_job_help(jobs: dict, pager: str | bool = False, verbose=False) -> None:
    if verbose:
        return print_job_help_verbose(jobs, pager=pager)

    width: int = max(len(j) for j in jobs) + 22

    console.print()
    for job, config in jobs.items():
        console.print(
            f" :white_circle:{f'[bold cyan]{job}[/] [dim]':.<{width}}[/] {config.get('help', '')}",
            highlight=False,
        )
    console.print()


def print_job_help_verbose(jobs: dict, pager: bool | str = False) -> None:
    table: Table = Table(
        show_header=False,
        padding=2,
        highlight=True,
        border_style=rich.style.Style(color="grey15"),
        expand=True,
    )
    row_styles: list[str] = ["grey7", "grey15"]

    table.add_column("Jobs", justify="left", max_width=60, no_wrap=False)
    table.add_column("Tasks", justify="left")

    for idx, (job, config) in enumerate(jobs.items()):
        text: list[str] = [
            f":white_circle:{f'[bold cyan]{job}[/]'}\n",
            f"[white]{config.get('help', '')}[/]",
        ]
        row: list[str | Syntax] = []

        after: str = ", ".join(config.get("after", []))
        if after:
            text.append("")
            text.append(rf"[white]After:[/] [bold yellow]{after}[/]")

        row.append("\n".join(text))

        for task in config.get("tasks", []):
            row.append(Syntax(task, "bash", background_color=row_styles[idx % 2]))

        table.add_row(*row, style=f"white on {row_styles[idx % 2]}")

    if not pager:
        console.print(table)
    else:
        with console.pager(styles=pager == "color"):
            console.print(table)


# ==============================================================================


def get_resolved_path(path: str | LazyValue, env: ConfigBox | None, workdir: Path | None = None) -> Path:
    "Resolves string or LazyValue into fully-qualified path."

    workdir = Path(".") if not workdir else workdir
    _path: Path = Path(path(env=env, workdir=workdir) if isinstance(path, LazyValue) else path)
    _path = _path.expanduser().resolve()
    return _path


# ==============================================================================


def check_project(project: str, fix_perms: bool = False) -> bool:
    "Check for path permissions and general sanity."

    program: Path = Path(sys.argv[0])
    home: Path = get_project_home()
    config: Path = home / "projects" / project

    # fmt: off
    return check_permissions(
        {
            config:            0o0600,
            home:              0o0700,
            home / "projects": 0o0700,
            program.parent:    0o0700, # bin/
            program:           0o0700, # bin/adhd
        },
        fix_perms = fix_perms,
    )
    # fmt: on


# ==============================================================================


class NonCallable:
    def __call__(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("This module is disabled.")

    def __bool__(self) -> bool:
        return False

    __nonzero__ = __bool__


# ==============================================================================


def realize(v: Any, *args, **kwargs) -> Any:
    "Evaluate v as a LazyObject, or return v"

    if not v:
        return v

    if isinstance(v, dict):
        for _k, _v in v.items():
            v[_k] = realize(_v, *args, **kwargs)
        return v
    elif isinstance(v, (list, tuple)):
        v = [realize(i, *args, **kwargs) for i in v]
        return v

    return v(*args, **kwargs) if callable(v) else v
