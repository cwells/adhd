"""
Check for updates to [cyan]adhd[/].

Queries Github repository for a new release of [cyan]adhd[/] and notifies user.

By default, the location of the [cyan]adhd[/] executable is presumed to be in the local repository.

Optional settings:
- [cyan]remote[/] Override the remote repository.
- [cyan]local[/] Override the local repository.
- [cyan]token[/] Provide Github token for accessing private repository.
- [cyan]ref[/] Git ref/tag to checkout (use HEAD to follow development).
- [cyan]update[/] Automatically perform a [blue]git pull[/] and checkout [cyan]ref[/] or latest tag.
"""

example = """
plugins:
  adhd-update:
    autoload: true
    remote: cwells/adhd
    local: ~/.adhd
    ref: "0.0.1"
    update: false
    token: q4Gir1fyourn4iwafflesqfhave432sickened099me053tqfetchqsmefAAthefabucket!Ba
"""

required_modules: dict[str, str] = {
    "git": "GitPython",
    "github": "PyGithub",
    "semver": "semver",
}
required_binaries: list[str] = []

import sys
from pathlib import Path

from lib.boot import missing_modules
from lib.util import ConfigBox, Style, console, get_program_bin
from plugins import BasePlugin, MetadataType

missing: list[str]

if missing := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]adhd[/] updater disabled, missing modules: {', '.join(missing)}\n")
else:
    from github import Github, Repository
    from git import Git, Repo  # type: ignore
    import semver

REMOTE_REPO = "cwells/adhd"
LOCAL_REPO = get_program_bin().parent


# ==============================================================================


class Plugin(BasePlugin):
    "Check Github for updates to [bold cyan]adhd[/]."

    key: str = "adhd-update"
    enabled: bool = not missing
    has_run: bool = False

    def load(self, config: ConfigBox, env: ConfigBox, verbose: bool = False) -> MetadataType:
        "Check Github for new release tag for adhd."

        if not self.enabled:
            self.print("support is disabled.", Style.ERROR)
            sys.exit(1)

        plugin_config: ConfigBox = config.plugins[self.key]
        remote: str = plugin_config.get("remote", REMOTE_REPO)
        local: Path = Path(plugin_config.get("local", LOCAL_REPO)).expanduser().resolve()
        token: str | None = plugin_config.get("token")
        ref: str | None = plugin_config.get("ref")
        update: bool | None = plugin_config.get("update", False)

        local_tag: str | None = self.get_local_tag(local)
        remote_tag: str | None = self.get_remote_tag(remote, token=token)

        if not remote_tag:
            return self.metadata

        if not local_tag or semver.compare(remote_tag, local_tag) > 0:
            self.print(
                f"An update to [bold cyan]adhd[/] is available ({local_tag} -> {remote_tag}). ",
                style=Style.PLUGIN_STATUS,
            )
            if update:
                self.update_local(local, ref or remote_tag)
                self.print(
                    f"updating [bold blue]{local}[/] to {ref or remote_tag}. Please restart your jobs.",
                    style=Style.PLUGIN_METHOD_SUCCESS,
                )
                raise SystemExit
            else:
                self.print(f"Run [bold white]git pull[/] from [bold blue]{local}[/].", style=Style.PLUGIN_STATUS)

        return self.metadata

    def get_local_tag(self, local: Path) -> str | None:
        repo: Repo = Repo(local)
        tags: list[str] = sorted(t.name for t in repo.tags)
        return tags[-1] if tags else None

    def get_remote_tag(self, remote: str, token: str | None) -> str | None:
        gh: GitHub = Github(token)  # type: ignore
        repo: Repository = gh.get_repo(remote)  # type: ignore
        tags: list[str] = sorted(t.name for t in repo.get_tags())  # type: ignore
        return tags[-1] if tags else None

    def update_local(self, local: Path, ref: str | None):
        git: Git = Git(local)
        repo: Repo = Repo(local)
        repo.remotes.origin.pull()
        if ref:
            git.checkout(ref)
