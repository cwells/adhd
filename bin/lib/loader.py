import os
import re
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable

try:
    import ruamel.yaml as yaml
except ImportError:
    try:
        import yaml
    except ImportError:
        raise SystemError("No YAML libraryfound.")

from yarl import URL

from .shell import shell
from .util import LazyValue, get_resolved_path, ConfigBox, realize, console

# ==============================================================================

builtins: dict[str, Any] = {
    "__DATE__": datetime.now().strftime("%Y%m%d"),
    "__TIME__": datetime.now().strftime("%H%M%S"),
}

# ==============================================================================


def find_deps(value: str | list[str]) -> set[str]:
    "Locate all env vars in a string and mark them as dependencies."
    deps: set[str] = set()

    if isinstance(value, list):
        for v in value:
            deps.update(find_deps(v))
    elif isinstance(value, str):
        if match := re.findall(r"\${(\w+)}", value):
            deps.update(match)

    return deps


# ==============================================================================


def populate_env_var(
    future: LazyValue,
    value: Any,
    env: ConfigBox | None = None,
    workdir: Path | None = None,
) -> Any:
    """
    Extracts the variable name from the node's value.
    Called via LazyValue at reification.
    """

    if env is None:
        env = ConfigBox()

    if future.dependencies:
        full_value: str = realize(value)
        for g in future.dependencies:
            if _v := os.environ.get(g, env.get(g, builtins.get(g))):
                full_value = full_value.replace(f"${{{g}}}", realize(_v, workdir=workdir, env=env))
        return full_value
    return realize(value, workdir=workdir, env=env)


def construct_env_vars(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> LazyValue:
    "Returns a LazyValue that will call populate_env_var() later."
    value: str = str(loader.construct_scalar(node))
    return LazyValue(populate_env_var, value, find_deps(value))


# ==============================================================================


def shell_eq_0(command: str, debug: bool, workdir: Path, env: ConfigBox) -> bool:
    "Executes command in subshell and return True if exit code is zero."
    process = shell(command=command, workdir=workdir, env=env)

    if debug:
        console.print(f"[bold]!shell_eq_0[/] {command=}")
        if isinstance(process.stderr, bytes):
            if output := process.stderr.decode().strip():
                console.print(f"[bold]!shell_eq_0[/] stderr: [bold red]{output}[/]")

    return process.returncode == 0


def shell_neq_0(command: str, debug: bool, workdir: Path, env: ConfigBox) -> bool:
    "Executes command in subshell and return True if exit code is non-zero."
    process = shell(command=command, workdir=workdir, env=env)

    if debug:
        console.print(f"[bold]!shell_neq_0[/] {command=}")
        if isinstance(process.stderr, bytes):
            if output := process.stderr.decode().strip():
                console.print(f"[bold]!shell_neq_0[/] stderr: [bold red]{output}[/]")

    return process.returncode != 0


def shell_stdout(command: str, debug: bool, workdir: Path, env: ConfigBox) -> str:
    "Executes command in subshell and returns output from command."
    process = shell(command=command, workdir=workdir, env=env, capture=True)

    if debug:
        console.print(f"[bold]!shell_stdout[/] {command=}")
        if isinstance(process.stderr, bytes):
            if output := process.stderr.decode().strip():
                console.print(f"[bold]!shell_stdout[/] stderr: [bold red]{output}[/]")

    if isinstance(process.stdout, bytes):
        output: str = process.stdout.decode().strip()
        if debug:
            console.print(f"[bold]!shell_stdout[/] stdout: [bold white]{output}[/]")
        return output
    return ""


def eval_shell_cmd(
    shell: Callable,
    future: LazyValue,
    value: str,
    workdir: Path,
    env: ConfigBox | None = None,
) -> Any:
    "Do the actual work of shelling out."

    value = populate_env_var(future, value, env, workdir)

    return shell(value, env=env or {}, workdir=workdir) if isinstance(value, str) else value


def construct_shell(shell: Callable, loader: yaml.SafeLoader, node: yaml.ScalarNode) -> LazyValue:
    "Execute a shell command."

    value: str = str(loader.construct_scalar(node))

    return LazyValue(partial(eval_shell_cmd, shell), value, find_deps(value))


# ==============================================================================


def eval_cat(
    sep: str,
    future: LazyValue,
    value: list,
    workdir: Path | None = None,
    env: ConfigBox | None = None,
) -> str:
    evaled: list[str] = [populate_env_var(future, v, env, workdir) for v in value]
    return sep.join(evaled)


def construct_cat(sep: str, loader: yaml.SafeLoader, node: yaml.SequenceNode) -> LazyValue:
    "Concatenate list of strings together with `sep` between each item."

    value: list = loader.construct_sequence(node)
    return LazyValue(partial(eval_cat, sep), value, find_deps(value))


# ==============================================================================


def eval_path(future: LazyValue, value: list, workdir: Path, env: ConfigBox | None = None) -> str:
    evaled: list[str] = [v(env=env, workdir=workdir) if isinstance(v, LazyValue) else v for v in value]
    path: Path = get_resolved_path("/".join(evaled), env=env, workdir=workdir)

    return str(path)


def construct_path(loader: yaml.SafeLoader, node: yaml.SequenceNode) -> LazyValue:
    "Concatenate list of strings into normalized path."

    value: list = []

    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        _v = loader.construct_scalar(node)
        value = [_v]

    if not value:
        raise TypeError("!path requires at least one item")

    return LazyValue(eval_path, value, find_deps(value))


# ==============================================================================


def eval_exists(exists: bool, future: LazyValue, value: list, workdir: Path, env: ConfigBox) -> bool:
    evaled: list[str] = [v(env=env, workdir=workdir) if isinstance(v, LazyValue) else v for v in value]
    path: Path = get_resolved_path("/".join(evaled), env=env, workdir=workdir)

    return path.exists() == exists


def construct_exists(exists: bool, loader: yaml.SafeLoader, node: yaml.SequenceNode) -> LazyValue:
    "Check if all of a list of files exists."

    value: list = []

    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        _v = loader.construct_scalar(node)
        value = [_v]

    if not value:
        raise TypeError("!path requires at least one item")

    return LazyValue(partial(eval_exists, exists), value, find_deps(value))


# ==============================================================================


def eval_url(exists: bool, future: LazyValue, value: list, workdir: Path, env: ConfigBox) -> str:
    evaled: list[str] = [populate_env_var(future, v, env, workdir) for v in value]
    url: URL = URL("/".join(evaled))

    return str(url)


def construct_url(loader: yaml.SafeLoader, node: yaml.SequenceNode) -> LazyValue:
    "Concatenate list of strings with no spaces and see if its a url. Exciting stuff."

    value: list[str] = []

    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        _v = str(loader.construct_scalar(node))
        value = [_v]

    if not value:
        raise TypeError("!url requires at least one item")

    return LazyValue(eval_url, value, find_deps(value))


# ==============================================================================


def construct_include(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> Any:
    "Include another YAML file about here."

    include: Path = Path(str(loader.construct_scalar(node))).expanduser().resolve()

    with open(include, "r") as f:
        result = yaml.load(f, Loader=yaml.SafeLoader)
        return result


# ==============================================================================


def get_loader(debug: bool = False) -> type[yaml.SafeLoader]:
    "YAML loader with sweet custom tags."

    loader: type[yaml.SafeLoader] = yaml.SafeLoader

    loader.add_constructor("!env", construct_env_vars)
    loader.add_constructor("!shell_eq_0", partial(construct_shell, partial(shell_eq_0, debug=debug)))
    loader.add_constructor("!shell_neq_0", partial(construct_shell, partial(shell_neq_0, debug=debug)))
    loader.add_constructor("!shell_stdout", partial(construct_shell, partial(shell_stdout, debug=debug)))
    loader.add_constructor("!cat", partial(construct_cat, ""))
    loader.add_constructor("!cats", partial(construct_cat, " "))
    loader.add_constructor("!catn", partial(construct_cat, "\n"))
    loader.add_constructor("!url", construct_url)
    loader.add_constructor("!path", construct_path)
    loader.add_constructor("!include", construct_include)
    loader.add_constructor("!exists", partial(construct_exists, True))
    loader.add_constructor("!not_exists", partial(construct_exists, False))

    return loader
