import sys
from pathlib import Path
from typing import Any, Generator

import filelock
import rich.prompt
from plugins import BasePlugin, load_or_unload_plugin

from .util import (
    ConfigBox,
    LazyValue,
    Style,
    console,
    get_resolved_path,
    get_sorted_deps,
    realize,
    resolve_dependencies,
)

# ==============================================================================


def get_job(
    command: tuple[str, ...] | list[str] | str,
    job_config: ConfigBox,
    project_config: ConfigBox,
    process_env: ConfigBox,
    explain: bool = False,  # don't _eval values that we don't need
) -> ConfigBox:
    "Build a job structure from configuration."

    env: ConfigBox = ConfigBox({**process_env, **job_config.get("env", {})})
    home: str | LazyValue = job_config.get("home") or project_config.get("home", ".")
    tmp: str | LazyValue = job_config.get("tmp") or project_config.get("tmp", "./tmp")
    workdir: Path = get_resolved_path(home, env=env)
    tmpdir: Path = get_resolved_path(tmp, env=env)
    cmd: Any = realize(job_config.get("run", []), workdir=workdir, env=env)
    run: list = cmd if isinstance(cmd, list) else [cmd]
    run_env: dict[str, str] = resolve_dependencies(
        ConfigBox({**process_env, **job_config.get("env", {})}),
        workdir=workdir,
    )
    after: list[str] = _after if isinstance((_after := job_config.get("after", [])), list) else [_after]

    job: ConfigBox = ConfigBox(
        {
            "after": after,
            "env": ConfigBox(realize({**env, **run_env}, workdir=workdir, env=env)),
            "help": realize(job_config.get("help", "No help available."), workdir=workdir, env=env),
            "lock": job_config.get("lock", True),
            "name": command,
            "open": realize(job_config.get("open"), workdir=workdir, env=env),
            "run": run,
            "tmp": str(tmpdir),
            "workdir": str(workdir),
        }
    )

    if not explain:
        job.update(  # these are potentially expensive, and may not run if deps aren't installed
            {
                "capture": realize(job_config.get("capture", False), workdir=workdir, env=env),
                "confirm": realize(job_config.get("confirm"), workdir=workdir, env=env),
                "interactive": realize(job_config.get("interactive", False), workdir=workdir, env=env),
                "skip": realize(job_config.get("skip", lambda *_, **__: False), workdir=workdir, env=env),
                "sleep": int(realize(job_config.get("sleep", 0), workdir=workdir, env=env)),
            }
        )

        required: set[str] = {"run", "after", "open"}
        configured: set[str] = set(k for k, v in job.items() if v)

        if not configured & required:
            console.print(
                f"{Style.ERROR}Job configuration error: [bold]{command}[/] must have "
                f"at least one of [yellow]{'[/], [yellow]'.join(required)}[/]"
            )
            sys.exit(1)

    return job


# ==============================================================================


def get_jobs(
    command: tuple[str, ...],
    project_config: ConfigBox,
    process_env: ConfigBox,
    plugins: dict[str, BasePlugin],
    lock: filelock.FileLock,
    verbose: bool = False,
    debug: bool = False,
    explain: bool = False,
) -> Generator:
    """
    Determine whether we're going to use a pre-defined job from configuration, or
    if we're console.print a cli command and generate a list of job structures with
    their associated env and other configuration.
    """

    home: str | LazyValue = project_config.get("home", ".")
    tmp: str | LazyValue = project_config.get("tmp", "./tmp")
    workdir: Path = Path(home(project_config["env"]) if isinstance(home, LazyValue) else home)
    tmpdir: Path = Path(tmp(project_config["env"]) if isinstance(tmp, LazyValue) else tmp)
    jobs: dict[str, Any] = project_config.get("jobs", {})

    _cmd: str = command[0]
    _args: tuple[str, ...] = command[1:]  # TODO: use these if they exist

    if not command:
        console.print(f"No command given.")
        sys.exit(1)

    with lock:
        if load_or_unload_plugin(command, plugins, project_config, process_env, explain):
            # the user invoked plugin at cli
            return

    if _cmd in jobs:  # pre-defined jobs
        if confirm := jobs[_cmd].get("confirm"):
            _confirm = realize(confirm, workdir=workdir, env=process_env)
            if not rich.prompt.Confirm.ask(_confirm, default=False, console=console):
                if rich.prompt.Confirm.ask("Would you like to abort?", default=True, console=console):
                    raise SystemExit("Aborted by user request.\n")

        for dep in get_sorted_deps(_cmd, jobs, workdir=workdir, env=process_env):
            job_config: ConfigBox = jobs.get(dep, {})

            with lock:
                if load_or_unload_plugin(tuple(dep.split()), plugins, project_config, process_env, explain):
                    continue

            try:
                yield get_job(dep, job_config, project_config, process_env, explain=explain)
            except Exception as e:
                console.print(f"{Style.ERROR} job [bold cyan]{_cmd}[/] failed: [bold white]{e}[/]")
                if debug:
                    raise
                sys.exit(1)

    else:  # cli command
        cmd: str = " ".join(command)

        yield ConfigBox(
            {
                "capture": False,
                "debug": debug,
                "env": process_env,
                "help": "I can't explain this.",
                "interactive": True,
                "lock": False,
                "name": cmd,
                "skip": False,
                "sleep": 0,
                "run": [cmd],
                "tmp": str(tmpdir),
                "verbose": verbose,
                "workdir": str(workdir),
            }
        )
