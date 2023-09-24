import sys
from pathlib import Path
from typing import Any, Generator

from lib.util import ConfigBox, Style, console, get_sorted_deps, resolve_dependencies


def get_job(
    command: str,
    job_config: ConfigBox,
    project_config: ConfigBox,
    process_env: dict[str, str],
) -> ConfigBox:
    "Build a job structure from configuration."

    env: dict[str, Any] = {**process_env, **job_config.get("env", {})}

    def _eval(v: Any, *args, **kwargs) -> Any:
        if not v:
            return v

        if isinstance(v, dict):
            for _k, _v in v.items():
                v[_k] = _eval(_v)
            return v
        elif isinstance(v, (list, tuple)):
            v = [_eval(i) for i in v]
            return v

        return v(*args, **kwargs) if callable(v) else v

    cmd: Any = _eval(job_config.get("run", []), env)
    workdir: Path = Path(_eval(job_config.get("home", project_config.get("home", ".")), env=env))
    tmpdir: Path = Path(_eval(job_config.get("tmp", project_config.get("tmp", "/tmp")), env=env))
    tasks: list = [_eval(t, workdir=workdir, env=env) for t in (cmd if isinstance(cmd, list) else [cmd])]
    _urls = _eval(job_config.get("open"), workdir=workdir, env=env)
    _open: list = (
        [_eval(_o, workdir=workdir, env=env) for _o in (_urls if isinstance(_urls, list) else [_urls])]
        if _urls
        else []
    )
    _env: dict[str, str] = resolve_dependencies(job_config.get("env", ConfigBox()), workdir)

    job: ConfigBox = ConfigBox(
        {
            "name": command,
            "env": {**env, **_env},
            "workdir": str(workdir),
            "tmp": str(tmpdir),
            "tasks": tasks,
            "skip": _eval(job_config.get("skip", lambda *_, **__: False), workdir=workdir, env=env),
            "open": _open,
            "capture": _eval(job_config.get("capture", False), env=env),
            "interactive": _eval(job_config.get("interactive", False), workdir=workdir, env=env),
            "silent": job_config.get("silent"),
            "confirm": job_config.get("confirm"),
            "sleep": job_config.get("sleep", 0),
            "help": job_config.get("help", "No help available."),
        }
    )

    if not (job["tasks"] or job_config.get("after") or job_config.get("open")):
        console.print(f"{Style.ERROR}{command}: must have at least one command, dependency, or open directive.")
        sys.exit(1)

    return job


def get_jobs(command: list[str] | tuple[str, ...], project_config: ConfigBox, process_env: dict) -> Generator:
    """
    Determine whether we're going to use a pre-defined job from configuration, or
    if we're console.print a cli command and generate a list of job structures with
    their associated env and other configuration.
    """

    jobs: dict[str, Any] = project_config.get("jobs", {})
    workdir: Path = Path(project_config.get("home", "."))
    tmpdir: Path = Path(project_config.get("tmp", "/tmp"))

    if not command:
        console.print(f"No command given.")
        sys.exit(1)

    if command[0] in jobs:  # pre-defined jobs
        for _cmd in command:  # somehow this keeps the dep order. i don't trust it.
            for dep in get_sorted_deps(_cmd, jobs, workdir=workdir, env=process_env):
                job_config: ConfigBox = jobs.get(dep, {})
                yield get_job(dep, job_config, project_config, process_env)

    else:  # cli command
        cmd: str = " ".join(command)
        yield {
            "name": cmd,
            "env": process_env,
            "workdir": str(workdir),
            "tmp": str(tmpdir),
            "tasks": [cmd],
            "sleep": 0,
            "capture": False,
            "interactive": True,
            "silent": False,
            "skip": False,
            "help": "I can't explain this.",
        }
