#!/usr/bin/env python

#
# Add the following to your ~/.bashrc:
#
#     complete -C ~/.adhd/bin/bash_completion.py adhd
#
# or, if you've symlinked to a different name, say "~/.local/bin/foo",
#
#     complete -C ~/.adhd/bin/bash_completion.py foo
#

import json
import sys
from pathlib import Path
from typing import Any

import ruamel.yaml as yaml
from lib.loader import get_loader


def get_project_jobs(project: Path) -> list[str]:
    conf: dict[str, Any] = {}

    try:
        conf = yaml.load(open(project, "r"), Loader=get_loader())
    except:
        pass

    return list(str(key) for key in conf.get("jobs", []))


def load_projects(home: str) -> dict[str, list[str]]:
    install_home = Path(f"~/.{home}").expanduser().resolve()
    projects_home = install_home / "projects"
    cache: Path = projects_home / ".completion.cache"
    cache_dirty: bool = False
    projects: dict[str, list[str]] = {}

    if cache.exists():
        projects = json.load(cache.open("r"))

    for project in projects_home.glob("*.yaml"):
        if not project.stem in projects or project.stat().st_mtime > cache.stat().st_mtime:
            projects[project.stem] = get_project_jobs(project)
            cache_dirty = True

    if cache_dirty:
        cache.open("w").write(json.dumps(projects))

    return projects


def completion_hook(cmd: str, curr_word: str, prev_word: str) -> list[str]:
    projects: dict[str, list[str]] = load_projects(home=cmd)

    if prev_word in projects:
        jobs = projects[prev_word]
        return [j for j in jobs if j.startswith(curr_word)]

    elif prev_word == cmd:
        return [p for p in projects if p.startswith(curr_word)]

    return []


def main():
    if results := completion_hook(*sys.argv[1:]):
        print("\n".join(results))


if __name__ == "__main__":
    main()
