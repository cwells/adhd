# What is this?

`adhd` is a small Python script for managing development environments for
multiple Python projects (it can reasonably be used for most anything, but it
has a Python-oriented focus on features).

If you're the sort of person who works on a lot of individual development
projects, each with its own unique build/run/deploy steps, `adhd` provides
a way of managing that without needing to revisit the project's README.

`adhd` is similar to a `make` in that you can define jobs to be run, and those
jobs in turn can define dependent tasks that will also be run. Tasks can be
conditionally run depending on the return codes of user-defined shell commands.

`adhd` has the following features:

- Automatic creation and activation of a Python virtual environment.
- Automatic installation of Python dependencies via `requirements.txt`.
- Automatic check of `requirements.txt` for updates.
- Automatic AWS MFA session management.
- Automatic launching of web pages.
- User-defined jobs with dependency resolution and ability to skip jobs based on
  the output of shell commands.
- User-defined environment variables with dependency resolution.
- Ability to run arbitrary shell commands from the CLI.
- Configuration can be kept outside project's git repository.
- Does not need to be run from project directory.
- Reasonably self-documenting project configuration.
- Manages multiple projects, and allows creating a common interface for varied
  development environments.

# CLI

The `adhd` CLI has the following interface:

```
Usage: adhd [OPTIONS] PROJECT [COMMAND]...

Options:
  --home / --no-home   Change to project HOME directory
  -e, --env ENV        Define env var(s) from CLI
  -p, --plugin PLUGIN  Manage plugins using `<plugin>:[on|off]`
  --dry-run            Don't actually execute anything
  --help-jobs          Display available jobs and help text
  --explain            Display help text from job and its dependencies
  -v, --verbose        Increase verbosity, send stdout of all jobs to console
  -f, --force          Bypass skip checks
  --help               Show this message and exit
```

## Examples

Enter a virtual environment:

```bash
$ adhd myproject -- bash
```

Run a predefined job to start `./manage.py shell`:

```bash
$ adhd myproject django/shell
```

> If you run arbitrary shell commands, remember to put `--` before the command
so that your shell knows which options are for `adhd` and which are for the
command.

# Installation

There is no install. Extract the archive (or `git clone`) into `~/.adhd` and
create a symlink on your `$PATH` to `~/.adhd/bin/adhd`, e.g.

```bash
$ ln -s ~/.adhd/bin/adhd ~/.local/bin/adhd
```

The adhd configuration is dynamic, based upon the name of the executable (by
default `adhd`). If your executable is named `adhd`, then the config directory
will be `~./adhd`. If you create a symlink

```bash
$ ln -s ~/.adhd/bin/adhd ~/.local/bin/woot
```

then the configuration will be looked for in `~/.woot`. This allows you to manage
multiple versions of `adhd` and even customize the code on a per-installation
basis. No need to pin the version of `adhd`.

An example config dir will look something like this:

    ~/.adhd/
        ├── bin
        │   └── adhd
        └── projects
            ├── project1.yaml
            ├── project2.yaml
            ├── ...
            └── projectX.yaml

# Configuration

```yaml
home: [str]                   # path to project directory
venv: Optional[str]           # path to virtual environment
tmp: Optional[str]            # path to store temporary files

include: Optional[list[str]]  # optional paths to include files

python:
  venv: [str]                 # path to project's virtual env
  requirements: [str]         # path to requirements.txt

aws:
  profile: [str]              # AWS CLI profile (from ~/.aws/credentials)
  username: [str]             # AWS username
  account: [str]              # AWS account ID
  mfa:
    device: [str]             # last part of MFA device's ARN
    expiry: [int]             # TTL in seconds for token expiry

jobs:
  <identifier>:
      command: str | list[str]           # the command(s) to be run
      depends: Optional[str | list[str]] # jobs that this job depends upon
      env: Optional[dict[str, Any]]      # define job-specific env vars
      help: Optional[str]                # help text for this job
      home: Optional[str]                # ff not set defaults to global value
      interactive: Optional[bool]        # let output go to the console
      open: Optional[str | list[str]]    # URI(s) to open after command
      skip: Optional[bool]               # skip dependency if value is True
      sleep: Optional[int]               # seconds to sleep after executing command

<identifier>:
  env: Optional[dict[str, Any]]  # define global environment variables
```

# Custom YAML tags

## !env

> Access and set environment variables

`!env` performs variable substitution on strings containing `${var}`. If a the
config references an undefined variable, the program leave the reference intact,
assuming the subshell will be able to resolve it.

```yaml
ARCHIVE: !env ${USER}-archive.tgz
```

Note that there are two phases for variable substitution: assembly-time (while
evaluating the YAML source) and run-time (in the shell environment), so
`FOO: ${BAR}` would simply evaluate to the literal string `"${BAR}"`, which is
generally what you want, as `$BAR` will presumably be in the environment.

On the other hand, `FOO: !env ${BAR}` causes the program to attempt to resolve
the value of `${BAR}` as soon as possible so that it can be used in other parts
of the configuration. As such, a dependency-resolution tree is maintained to
ensure required values are present when the variable is evaluated.

This is why you can use variables with other tags such as `!shell`: the shell
just ends up using the unevaluated string, but it doesn't matter since the value
will be present in the environment.

One reason to use `!env` is that environment variables are not passed through
from the parent shell by default (`$PATH` being a notable exception).
If you want to pass through a variable, use the following form:

```yaml
HOME: !env ${HOME}
```
Without `!env`, `${HOME}` would just be the plain string and be empty in the
subshell.

There are built-in variables that can be used in the config, but won't be
passed to the user's command:

- `${__DATE__}` - static date string, in the format `"%Y%m%d"`
- `${__TIME__}` - static time string, in the format `"%H%M%S"`

Example use:

```yaml
ARCHIVE: !env ../../staging_dataset_${__DATE__}.tar.gz
```

## !shell

> Execute arbitrary shell commands and use their results. There are a handful of variants:

`!shell_eq_0 <command>` executes the command in a subshell, and evaluates to
`true` if the exit status of the command is zero, otherwise evaluates to
`false`.

Inverse functionality is available as `!shell_neq_0`.

```yaml
skip: !shell_eq_0 fuser -s 8000/tcp
```

In the above example, the job would be skipped if a process were seen listening
on port `8000/tcp`.


`!shell_stdout command` executes the command in a subshell, and evaluates to
the value the command writes to `stdout`.

```yaml
EXTERNAL_ROUTE: !shell_stdout ip -json route get 1 | jq -r '.[0].prefsrc'
```

In the above example, `EXTERNAL_ROUTE` would be the IP address of the machine's
external interface.

## !cat, !path, !url

> string concatenation

- `!cat` concatenates a list of strings with a single space between each item.
- `!path` concatenates a list of strings into a path and returns a normalized
path (`~` and `..` will be substituted and collapsed).
- `!url` concatenates a list of strings into a URL.

```yaml
SECRET: !cat [ because, is, hat ]
```
```yaml
API_ENDPOINT: !url [ https://domain.com/cust/, *cust_id, /api ]
```
```yaml
DATA_DIR: !path [ ~, foo, bar, data_dir ]
```

# Include other YAML files

It may be useful to load other YAML files (e.g. for common env variables in
project home directory). The format of the included file is exactly the same as
the primary project file. Dictionaries will be recursively merged.

# A working example

A working Django app is included in the `projects/` directory. It requires no
setup, just run `adhd example django/up`.

# Jobs

You can see available jobs using the `--help-jobs` option:

```bash
$ adhd myproject --help-jobs
```

which would output

```
           world Opens relevant tabs in broswer, and project directory in vscode.
        stack/up Brings up all required services.
      stack/down Stops (but doesn't destroy) entire stack.
   stack/destroy Destroys all stack containers as well as its virtual env.
       django/up Starts the Django web server at http://localhost:8000/
     django/down Stops the Django web server.
  django/destroy Deletes the Python virtual env.
     django/seed Seeds the database with test data.
    django/shell Start an interactive Django shell.
       docker/up Start Docker services. Mailpit is at http://localhost:8025.
     docker/down Stops Docker services.
  docker/destroy Stops Docker services, and destroys all containers.
            test Run the test suite.
```

And don't forget that you can run arbitrary shell commands. Assuming you have
configured AWS, you can try something like:

```bash
$ adhd myproject -- aws s3 ls
```

which would output

```
Finished installing Python requirements
Starting aws s3 ls
2020-04-28 11:27:21 my-prod-files
2020-05-21 14:07:06 my-stage-files
```

You can also enter the virtual environment just by spawning a subshell:

```bash
$ adhd myproject bash
Finished installing Python requirements
Starting bash
$ python
Python 3.11.4 (main, Jun  7 2023, 00:00:00) [GCC 13.1.1 20230511 (Red Hat 13.1.1-2)] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import django
>>> django.setup()
>>>
```

# Plugins

You may disable plugins on the command line. For example, if you want to run a
shell but not be prompted for an MFA code, you can use:

```
ombu va --plugin aws:off bash
```