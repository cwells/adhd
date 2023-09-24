"""
[bold cyan]Include external YAML files.[/]

Note that inclusion happens relative to the document root, _not_ in-place within
the plugins section.

  include:
  - file1.yaml
  - !path [ "~", projects/file2.yaml ]
"""

from typing import Any

import yaml
from lib.plugins import PluginTarget
from lib.util import ConfigBox, console


# ==============================================================================


key: str | None = None
target: PluginTarget = PluginTarget.CONF
has_run: bool = False


def load(
    config: ConfigBox,
    env: dict[str, Any],
    verbose: bool = False,
) -> ConfigBox:
    "Include YAML files"

    conf: ConfigBox = ConfigBox()

    for _include in config:
        with open(_include, "r") as _file:
            conf.update(yaml.load(_file.read(), Loader=yaml.FullLoader))
        if verbose:
            console.print(f"Included {_include}")

    return conf
