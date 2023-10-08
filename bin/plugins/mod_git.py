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

    def load(self, config: ConfigBox, env: ConfigBox, verbose: bool = False) -> MetadataType:
        "Clone a git repo."

        if not self.enabled:
            self.print(f"support is disabled. Please install plugin requirements.", Style.ERROR)
            sys.exit(1)

        repo: git.Repo  # type: ignore
        remote: str | None
        local: Path
        branch: str | None

        if not (remote := config.get("remote")):
            self.print(f"missing key: [bold cyan]plugins.git.remote[/]", Style.ERROR)
            sys.exit(2)

        if not (branch := config.get("branch")):
            self.print(f"missing key: [bold cyan]plugins.git.branch[/]", Style.ERROR)
            sys.exit(2)

        if _local := config.get("local"):
            local = Path(_local).expanduser().resolve()
        else:
            self.print(f"missing key: [bold cyan]plugins.git.local[/]", Style.ERROR)
            sys.exit(2)

        self.remote: str = remote
        self.local: Path = local
        self.branch: str = branch

        if (local / ".git").exists():
            if self.verbose:
                self.print(f"git.clone: [bold cyan]{local}[/] is already initialized.", Style.SKIP)
            return self.metadata

        if local.exists() and any(local.iterdir()):
            self.print(f"[bold cyan]{local}[/] exists and is not empty", Style.ERROR)
            sys.exit(2)
        else:
            with console.status(f"Cloning git repository {remote} into {local}"):
                self.clone(config, env)
            self.print(f"cloning git repository into {remote}", Style.FINISHED)
        return self.metadata

    def clone(self, config: ConfigBox, env: ConfigBox) -> None:
        try:
            repo = git.Repo.clone_from(self.remote, self.local, branch=self.branch)  # type: ignore
        except Exception as e:
            _exit(e)
