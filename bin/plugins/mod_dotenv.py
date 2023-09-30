"""
[bold cyan]Import .env files.[/]

Note that inclusion happens relative to the document root, _not_ in-place within
the plugins section.

  dotenv:
  - !path [ "~", projects/.env ]
  - !path [ "~", projects/.dev.env ]
"""

import sys
from pathlib import Path
from typing import Any

from lib.boot import missing_modules
from lib.plugins import BasePlugin, PluginTarget
from lib.util import ConfigBox, console, Style, check_permissions, NonCallable

if missing_modules(["dotenv"]):
    print("python-dotenv not found: .env support disabled.")
    dotenv_values = None
else:
    from dotenv import dotenv_values


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "dotenv"
    enabled: bool = dotenv_values is not None
    target: PluginTarget = PluginTarget.ENV
    has_run: bool = False

    def load(self, config: ConfigBox, env: dict[str, Any], verbose: bool = False) -> ConfigBox:
        "Import .env files. The circle is complete."

        if not self.enabled:  # we were unable to import module
            console.print(f"{Style.ERROR}dotenv support is disabled. Please install python-dotenv package.")
            sys.exit(1)

        conf: ConfigBox = ConfigBox()
        files: list[str] = config.get("files", [])
        secure_paths: dict[Path, int] = {
            Path(f).expanduser().resolve(): 0o0600 for f in files
        }  # FIXME: too strict - should allow o+r ?

        if not check_permissions(secure_paths):
            sys.exit(2)

        _env: dict[str, str | None] | None

        for filename in files:
            path: Path = Path(filename).expanduser().resolve()
            if not path.exists():
                console.print(f"{Style.ERROR}No such .env file {path}")
                continue

            if _env := dotenv_values(dotenv_path=path):  # type: ignore
                conf.update(_env)
            if verbose:
                console.print(f"Imported environment from {filename}")

        return conf
