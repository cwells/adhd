# adhd

`adhd` is a small Python program for managing development environments for
multiple Python projects (it can reasonably be used for most anything, but it
has a Python-oriented focus on features).

If you're the sort of person who works on a lot of individual development
projects, each with its own unique build/run/deploy steps, `adhd` provides
a way of managing that without needing to revisit the project's README.
If you're the sort of person who also forgets details a lot (maybe because
you have ADHD), this tool can be quite helpful.

`adhd` is similar to a `make` in that you can define jobs to be run, and those
jobs in turn can define dependent jobs that will also be run. Jobs can be
conditionally run depending on the return codes of user-defined shell commands.

The original purpose of `adhd` was as a replacement for .env files, but of course
running jobs made sense, and then you need job ordering and dependencies, and plugins
sound cool, So here we are.

> It is important to note that `adhd` is not meant to replace `make` or other tools, and it's not expected that your `adhd` config will live in the project directory to be shared with others. Rather `adhd` is a way to personalize and simplify _your_ workflow without impacting other people working on the same project. In many cases an `adhd` project will be nothing more than a thin wrapper around `make`.

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

# Quickstart / tldr;

- Install:

        git clone git@github.com:cwells/adhd.git ~/.adhd
        pip install -r ~/.adhd/requirements.txt
        chmod +x ~/.adhd/bin/adhd
        ln -s ~/.adhd/bin/adhd ~/.local/bin/adhd

- Start the included Django app:

        adhd example django/up

- Stop the Django app:

        adhd example django/down

- Cleanup (you'll be prompted to remove directory):

        adhd example django/destroy

- To see the example config (you probably should have read this first):

        cat ~/.adhd/projects/example.yaml

# CLI

The `adhd` CLI has the following interface:

    $ adhd example --help
    Usage: adhd [OPTIONS] PROJECT [COMMAND]..
    Options:
      --home / --no-home   Change to project HOME directory
      -e, --env ENV        Define env var(s) from CLI
      -p, --plugin PLUGIN  Manage plugins using plugin:[on|off]
      --help-jobs          Display available jobs and help text
      --help-plugins       Display available plugins and help text
      --explain            Display help text from job and its dependencies
      -v, --verbose        Send stdout of all jobs to console
      --debug              Generate extremely verbose output
      -f, --force          Bypass skip checks
      --help               Show this message and exit

## Examples

Enter a virtual environment:

    adhd example -- bash

Run a predefined job to start `./manage.py shell`:

    adhd example django/shell

> If you run arbitrary shell commands, remember to put `--` before the command so that your shell knows which options are for `adhd` and which are for the command.

# Installation

There is no install. Extract the archive (or `git clone`) into `~/.adhd` and
create a symlink on your `$PATH` to `~/.adhd/bin/adhd`, e.g.

    ln -s ~/.adhd/bin/adhd ~/.local/bin/adhd

The adhd configuration is dynamic, based upon the name of the executable (by
default `adhd`). If your executable is named `adhd`, then the config directory
will be `~/.adhd`. If you create a symlink

    ln -s ~/.adhd/bin/adhd ~/.local/bin/woot

then the configuration will be looked for in `~/.woot` when you run `woot`. This allows you to simply manage multiple versions of `adhd` across disparate projects without involving packages.

# A working example

A working Django project is included in the [`projects/`](https://github.com/cwells/adhd/tree/main/projects) directory. It requires no
setup, just run:

    adhd example django/up

This will:
- create a virtualenv and install Django
- run `django-admin startproject` (Django docs [here](https://docs.djangoproject.com/en/4.2/intro/tutorial01/#creating-a-project)) to create a basic Django project
- and finally, open the front page in your browser to verify functionality.

# Configuration


An typical config dir will look something like this:

      .adhd
      ├── bin/
      │   ├── adhd/
      │   ├── lib/
      │   └── plugins/
      ├── projects/
      │   ├── project1.yaml
      │   ├── project2.yaml
      │   ├── project3.yaml
      │   ├── ...
      │   └── projectn.yaml
      └── requirements.txt


Each project file will have the following form:

```yaml
home: [str]                   # path to project directory
venv: Optional[str]           # path to virtual environment
tmp: Optional[str]            # path to store temporary files

plugins:
  python:
    autoload: [bool]            # autoload load this plugin on startup
    venv: [str]                 # path to project's virtual env
    requirements: [str]         # path to requirements.txt

  aws:
    autoload: [bool]            # autoload load this plugin on startup
    profile: [str]              # AWS CLI profile (from ~/.aws/credentials)
    username: [str]             # AWS username
    account: [str]              # AWS account ID
    mfa:
      device: [str]             # last part of MFA device's ARN
      expiry: [int]             # TTL in seconds for token expiry

jobs:
  <identifier>:
      run: str | list[str]               # the command(s) to be run
      after: Optional[str | list[str]]   # jobs or plugins that this job depends upon
      env: Optional[dict[str, Any]]      # define job-specific env vars
      help: Optional[str]                # help text for this job
      home: Optional[str]                # ff not set defaults to global value
      interactive: Optional[bool]        # let output go to the console
      open: Optional[str | list[str]]    # URI(s) to open after command
      skip: Optional[bool]               # skip dependency if value is True
      sleep: Optional[int]               # seconds to sleep after executing command
      confirm: Optional[str]             # Ask user a y/n question and abort if no

<identifier>:
  env: Optional[dict[str, Any]]  # define global environment variables
```

> The `confirm` directive allows for the use of colors and emoji as described in the [Rich documentation](https://rich.readthedocs.io/en/stable/appendix/colors.html).

# Custom YAML tags

## !env

> Access and set environment variables

`!env` performs variable substitution on strings containing `${var}`. If a the
config references an undefined variable, the program leave the reference intact,
assuming the subshell will be able to resolve it.

  ```yaml
    ARCHIVE: !env ${USER}-archive.tgz
  ```

> Note that there are two phases for variable substitution: assembly-time (while evaluating the YAML source) and run-time (in the shell environment), so `FOO: ${BAR}` would simply evaluate to the literal string `"${BAR}"`, which is generally what you want, as `$BAR` will presumably be in the environment when it's needed.
>
> On the other hand, `FOO: !env ${BAR}` causes the program to attempt to resolve the value of `${BAR}` as soon as possible so that it can be used in other parts of the configuration. As such, a dependency-resolution tree is maintained to ensure required values are present when the variable is evaluated.
>
> This is why you can use variables with other tags such as `!shell`: the shell just ends up using the unevaluated string, but it doesn't matter since the value will be present in the environment.

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

## !shell_eq_0, !shell_neq_0, !shell_stdout

> Execute arbitrary shell commands and use their results. There are a handful of variants:

`!shell_eq_0 <command>` executes the command in a subshell, and evaluates to `true` if the exit status of the command is zero, otherwise evaluates to
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

## !cat, !cats, !path, !url, !exists

> string concatenation

- `!cat` concatenates a list of strings with no space between each item.
- `!cats` concatenates a list of strings with a single space between each item.
- `!path` concatenates a list of strings with '/' and returns a normalized path (`~` and `..` will be substituted and collapsed).
- `!url` concatenates a list of strings with '/' into a URL.
- `!exists` concatenates list of strings into a path and returns True if path exists.
- `!not_exists` concatenates list of strings into a path and returns False if path exists.

  ```yaml
    SECRET: !cat [ because, is, hat ]
    API_ENDPOINT: !url [ https://domain.com/cust/, *cust_id, /api ]
    DATA_DIR: !path [ "~", foo, bar, data_dir ]
    binary: !exists [ "~/.bin", *bin_name  ]
  ```

> CAVEAT: `!exists` and `!path` tags will not have the project home as their working
> directory due to the fact that this information isn't available when they
> are evaluated. This means you must prefix any paths with `*home`, e.g.:
>
> ```yaml
>    skip: !exists [ *home, "/tmp/process.pid" ]
> ```
> This is unlike `run` directives, which will have the project home as their
> current working directory. This is a bug and will be addressed in a future
> release.


## !include

It may be useful to load other YAML files (e.g. for common env variables in
project home directory). The format of the included file is exactly the same as
the primary project file. Dictionaries will be recursively merged.

  ```yaml
    !include more.yaml
  ```

# Jobs

You may define jobs in the `jobs` section of the YAML config file. A job can
depend on other jobs or plugins, indicated by the key `after`:

  ```yaml
    django/up:
      run: ./manage.py runserver &
      skip: !shell_eq_0 fuser -s 8000/tcp
      after: [ plugin:python, django/bootstrap, django/migrate ]
  ```

If `django/up` is run, it will first load the `python` plugin, then run
`django/bootstrap` and `django/migrate` (and these in turn may have other
dependencies). If you don't autoload want a job to run, you can add the `skip`
directive, followed by a test that evaluates the output of a shell command.

Jobs and plugins are only run once, regardless of how many other jobs may depend
on them.

# Tasks

Every job can have one or more tasks that compose it (it's possible to have no
tasks and only have dependencies). Tasks are simply shell commands, run in sequence.

A job with a single task:

    django/up:
      help: Start the Django web server.
      run: "./manage.py runserver &"
      skip: !shell_eq_0 fuser -s 8000/tcp
      interactive: true
      after: [ plugin:python, plugin:aws, docker/up, django/seed ]

A job with no tasks:

    stack/up:
      help: Bring up all required services.
      after: [ docker/up, django/up, ngrok/up ]

Tasks typically run in their own subprocess. Each item in the `run` list will
be run in a separate process:

    db/sync:
      help: Sync staging database to dev database.
      run:
      - echo "Starting database sync..."
      - pg_dumpall staging > db.sql
      - psql dev < db.sql
      - rm -f db.sql
      - echo "Finished syncing database."
      confirm: \nSync staging database to dev?

This means that you cannot set an env variable in one line and then use it in
the next. Each task gets a clean slate.

If you want tasks to share a subprocess (similar to `make`'s `.ONESHELL`
option), use the following format:

    db/sync:
      help: Sync staging database to dev database.
      run: |
        echo "Starting database sync..."
        TMPFILE=db.sql
        pg_dumpall staging > ${TMPFILE}
        psql dev < ${TMPFILE}
        rm -f ${TMPFILE}
        echo "Finished syncing database."
      confirm: \nSync staging database to dev?

# The CLI

You can see available jobs using the `--help-jobs` option:

    adhd example --help-jobs

which would output

    adhd example --help-jobs

    ⚪ up ................ Run django/up and open the front and admin pages.
    ⚪ down .............. Alias for django/down.
    ⚪ shell ............. Open a shell with the Python virtual environment activated.
    ⚪ django/up ......... Start the Django web server.
    ⚪ django/shell ...... Start an interactive Django Python REPL.
    ⚪ django/down ....... Stop the Django web server.
    ⚪ django/migrate .... Run Django database migrations
    ⚪ django/bootstrap .. Bootstrap the Django project.
    ⚪ django/destroy .... Remove installation directory (you will be prompted first).

And don't forget that you can run arbitrary shell commands. Assuming you have
configured the AWS plugin, you can try something like:

    adhd example -- aws s3 ls

which would output something like:

    Starting aws s3 ls
    2020-04-28 11:27:21 my-prod-files
    2020-05-21 14:07:06 my-stage-files

You can also enter the virtual environment just by spawning a subshell:

    $ adhd example bash -p python:on
    ⚫ Finished installing Python packages
    $ python
    Python 3.11.4 (main, Jun  7 2023, 00:00:00) [GCC 13.1.1 20230511 (Red Hat 13.1.1-2)] on linux
    Type "help", "copyright", "credits" or "license" for more information.
    >>> import django
    >>> django.setup()
    >>>

If you have `autoload: false` for the `python` plugin, then the virtual env won't be started.
You can forcibly load the plugin from the cli, which will cause the virtual env to be activated:

    adhd example --plugin python:on bash

Alternately, you can just add another command to make this automatic:

  ```yaml
    jobs:
      shell:
        help: Enter the Python virtual environment for this project.
        run: !env ${SHELL}
        interactive: true
        silent: true
        after: plugin:python
  ```

and then run

    adhd example shell

# Plugins

You can get a list of available plugins and their help with:

    $ adhd example --help-plugins

    ⚫ mod_aws Configure AWS session with MFA.

      aws:
        profile: default      # profile name from .aws/credentials
        username: john.doe    # AWS username
        account: 123456789012 # AWS account ID
        region: eu-west-1     # AWS region
        mfa:
          device: MyDevice    # last part of ARN "arn:aws:iam::123456789012:mfa/MyDevice"
          expiry: 86400       # TTL for token (will prompt for MFA code upon expiry)

    Session will be cached in "tmp" for "expiry" seconds and you wont be prompted
    for MFA code until that time, even across multple invokations and multiple shells.

    ⚫ mod_python Configure Python virtual environment.

      python:
        venv: ~/myproject/.venv                    # location venv will be created
        requirements: ~/myproject/requirements.txt # optional requirements.txt to be installed
        packages: [ requests, PyYAML==5.4.1 ]      # additional packages to install

    If `virtualenv` package is missing, plugin will still work with an existing
    virtual environment, but won't be able to create a new one.

You may enable or disable individual plugins on the command line.

    adhd example --plugin aws:off bash    # don't prompt for mfa code
    adhd example --plugin python:on bash  # ensure we enter venv

Plugins can be enabled in the `plugins` section of your project config:

  ```yaml
    plugins:
      python:
        autoload: false
        venv: !path [ *home, venv ]
        packages: [ Django ]

      dotenv:
        autoload: true
        files:
        - !path [ ~/.test.env ]
  ```

The `autoload` key specifies whether to load the plugin at startup, or to only make
it available as a job dependency. Note that if one dependency loads a plugin, it
will be available from that point forward.

  ```yaml
    jobs:
      aws/shell:
        help: Disable AWS authentication.
        after: plugin:aws
  ```

Some plugins support unloading as a dependency using `unplug` instead of `plugin`:

  ```yaml
    jobs:
      safe/shell:
        help: Disable AWS authentication.
        after: unplug:aws
  ```

  Note that any processes that were already run will not be affected by unloading
  a plugin.

# TODO

- additional planned plugins:
  - `mod_git` - clone a project git repo.
  - `mod_asdf` - select Python version.
  - `mod_ngrok` - manage ngrok tunnels.
- get `!exists` and `!path` to operate in project home.
- more verbosity when verbose.