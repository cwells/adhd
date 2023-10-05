"""
Clone a git repository.
"""

example = """
plugins:
  git:
    remote: https://github.com/cwells/adhd
    local: ~/projects/adhd
    branch: master
"""

required_modules: dict[str, str] = {"git": "GitPython"}
required_binaries: list[str] = ["git"]

import sys
from pathlib import Path
from typing import Any

from lib.boot import missing_binaries, missing_modules
from lib.util import ConfigBox, console, Style, _exit
from plugins import BasePlugin, MetadataType

missing: list[str]

if missing := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]git[/] disabled, missing modules: {', '.join(missing)}\n")
    git = None
else:
    import git

if missing := missing_binaries(required_binaries):
    console.print(f"Plugin [bold blue]git[/] disabled, missing binaries: {', '.join(missing)}\n")
    git = None


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "git"
    enabled: bool = bool(git)
    has_run: bool = False

    def load(self, config: ConfigBox, env: dict[str, Any], verbose: bool = False) -> MetadataType:
        "Clone a git repo."

        if not self.enabled:
            console.print(f"{Style.ERROR}git support is disabled. Please install plugin requirements.")
            sys.exit(1)

        repo: git.Repo  # type: ignore
        remote: str | None
        local: Path
        branch: str | None

        if not (remote := config.get("remote")):
            console.print(f"{Style.ERROR}Missing key: [bold cyan]plugins.git.remote[/]")
            sys.exit(2)

        if not (branch := config.get("branch")):
            console.print(f"{Style.ERROR}Missing key: [bold cyan]plugins.git.branch[/]")
            sys.exit(2)

        if _local := config.get("local"):
            local = Path(_local).expanduser().resolve()
        else:
            console.print(f"{Style.ERROR}Missing key: [bold cyan]plugins.git.local[/]")
            sys.exit(2)

        self.remote: str = remote
        self.local: Path = local
        self.branch: str = branch

        if local.exists() and any(local.iterdir()):
            console.print(f"{Style.ERROR}git: [bold cyan]{local}[/] exists and is not empty")
            sys.exit(2)
        else:
            with console.status(f"Cloning git repository {remote} into {local}"):
                self.clone(config, env)
            console.print(f"{Style.FINISHED}cloning git repository into {remote}")
        return self.metadata

    def clone(self, config: ConfigBox, env: dict[str, Any]) -> None:
        try:
            repo = git.Repo.clone_from(self.remote, self.local, branch=self.branch)  # type: ignore
        except Exception as e:
            _exit(e)
