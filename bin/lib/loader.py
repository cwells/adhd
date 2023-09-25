import os
import re
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable

import yaml
from yarl import URL

from .shell import shell
from .util import get_resolved_path, LazyValue

# ==============================================================================

builtins: dict[str, Any] = {
    "__DATE__": datetime.now().strftime("%Y%m%d"),
    "__TIME__": datetime.now().strftime("%H%M%S"),
}

# ==============================================================================


def find_deps(value) -> set[str]:
    deps: set[str] = set()

    if isinstance(value, str):
        if match := re.findall(r"\${(\w+)}", value):
            deps.update(match)

    return deps


# ==============================================================================


def populate_env_var(
    future: LazyValue,
    value: Any,
    env: dict[str, Any] | None = None,
    workdir: Path | None = None,
) -> Any:
    """
    Extracts the variable name from the node's value.
    Called via LazyValue at reification.
    """

    if not isinstance(value, str):
        return value

    if env is None:
        env = {}

    if future.dependencies:
        full_value: str = value
        for g in future.dependencies:
            if _v := os.environ.get(g, env.get(g, builtins.get(g))):
                full_value = full_value.replace(f"${{{g}}}", str(_v))
        return full_value
    return value


def construct_env_vars(loader: yaml.FullLoader, node: yaml.ScalarNode) -> LazyValue:
    "Returns a LazyValue that will call populate_env_var() later."

    value: str = str(loader.construct_scalar(node))
    deps: set[str] = set()
    if match := re.findall(r"\${(\w+)}", value):
        deps.update(match)
    return LazyValue(populate_env_var, value, deps)


# ==============================================================================


def shell_eq_0(command: str, workdir: Path, env: dict[str, Any] | None = None) -> bool:
    "Executes command in subshell and return True if exit code is zero."
    return shell(command=command, workdir=workdir, env=env).returncode == 0


def shell_neq_0(command: str, workdir: Path, env: dict[str, Any] | None = None) -> bool:
    "Executes command in subshell and return True if exit code is non-zero."
    return shell(command=command, workdir=workdir, env=env).returncode != 0


def shell_stdout(command: str, workdir: Path, env: dict[str, Any] | None = None) -> str:
    "Executes command in subshell and returns output from command."
    result = shell(command=command, workdir=workdir, env=env, capture=True)
    if isinstance(result.stdout, bytes):
        return result.stdout.decode().strip()
    return ""


def eval_shell_cmd(
    shell: Callable,
    future: LazyValue,
    value: str,
    workdir: Path,
    env: dict[str, Any] | None = None,
) -> Any:
    "Do the actual work of shelling out."

    return shell(value, env=env or {}, workdir=workdir) if isinstance(value, str) else value


def construct_shell(shell: Callable, loader: yaml.FullLoader, node: yaml.ScalarNode) -> LazyValue:
    "Execute a shell command."

    value: str = str(loader.construct_scalar(node))

    return LazyValue(partial(eval_shell_cmd, shell), value, find_deps(value))


# ==============================================================================


def eval_cat(
    sep: str,
    future: LazyValue,
    value: list,
    workdir: Path,
    env: dict[str, Any] | None = None,
) -> str:
    evaled: list[str] = [v(env=env, workdir=workdir) if isinstance(v, LazyValue) else v for v in value]

    return sep.join(evaled)


def construct_cat(sep: str, loader: yaml.FullLoader, node: yaml.SequenceNode) -> LazyValue:
    "Concatenate list of strings together with `sep` between each item."

    value: list = loader.construct_sequence(node)
    deps: set[str] = set()

    return LazyValue(partial(eval_cat, sep), value, deps)


# ==============================================================================


def eval_path(
    future: LazyValue,
    value: list,
    workdir: Path,
    env: dict[str, Any] | None = None,
) -> str:
    evaled: list[str] = [v(env=env, workdir=workdir) if isinstance(v, LazyValue) else v for v in value]
    path: Path = get_resolved_path("/".join(evaled), env=env, workdir=workdir)

    return str(path)


def construct_path(loader: yaml.FullLoader, node: yaml.SequenceNode) -> LazyValue:
    "Concatenate list of strings into normalized path."

    value: list = []
    deps: set[str] = set()

    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        _v = loader.construct_scalar(node)
        deps.update(find_deps(_v))
        value = [_v]

    if not value:
        raise TypeError("!path requires at least one item")

    return LazyValue(eval_path, value, deps)


# ==============================================================================


def eval_exists(
    exists: bool,
    future: LazyValue,
    value: list,
    workdir: Path,
    env: dict[str, Any],
) -> bool:
    evaled: list[str] = [v(env=env, workdir=workdir) if isinstance(v, LazyValue) else v for v in value]
    path: Path = get_resolved_path("/".join(evaled), env=env, workdir=workdir)

    return path.exists() == exists


def construct_exists(exists: bool, loader: yaml.FullLoader, node: yaml.SequenceNode) -> LazyValue:
    "Check if all of a list of files exists."

    value: list = []
    deps: set[str] = set()

    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        _v = loader.construct_scalar(node)
        deps.update(find_deps(_v))
        value = [_v]

    if not value:
        raise TypeError("!path requires at least one item")

    return LazyValue(partial(eval_exists, exists), value, deps)


# ==============================================================================


def construct_url(loader: yaml.FullLoader, node: yaml.SequenceNode) -> str:
    "Concatenate list of strings with no spaces and see if its a url. Exciting stuff."

    items: list[str] = []

    if isinstance(node, yaml.SequenceNode):
        items = loader.construct_sequence(node)
    else:
        items = [str(loader.construct_scalar(node))]

    if not items or not items[-1]:
        raise TypeError("!url requires at least one item")

    url: URL = URL("".join(items))

    return str(url)


# ==============================================================================


def construct_include(loader: yaml.FullLoader, node: yaml.ScalarNode) -> Any:
    "Include another YAML file about here."

    include: Path = Path(str(loader.construct_scalar(node))).expanduser().resolve()

    with open(include, "r") as f:
        result = yaml.load(f, Loader=yaml.FullLoader)
        return result


# ==============================================================================


def get_loader() -> type[yaml.FullLoader]:
    "Custom loader with sweet custom tags."

    loader: type[yaml.FullLoader] = yaml.FullLoader

    loader.add_constructor("!env", construct_env_vars)
    loader.add_constructor("!shell_eq_0", partial(construct_shell, shell_eq_0))
    loader.add_constructor("!shell_neq_0", partial(construct_shell, shell_neq_0))
    loader.add_constructor("!shell_stdout", partial(construct_shell, shell_stdout))
    loader.add_constructor("!cat", partial(construct_cat, ""))
    loader.add_constructor("!cats", partial(construct_cat, " "))
    loader.add_constructor("!catn", partial(construct_cat, "\n"))
    loader.add_constructor("!url", construct_url)
    loader.add_constructor("!path", construct_path)
    loader.add_constructor("!include", construct_include)
    loader.add_constructor("!exists", partial(construct_exists, True))
    loader.add_constructor("!not_exists", partial(construct_exists, False))

    return loader
