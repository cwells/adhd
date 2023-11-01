"""
Configure AWS session with MFA.

Session will be cached in [cyan]tmp[/] for [cyan]expiry[/] seconds and you won't be prompted for MFA code until that time, even across multple invokations and multiple shells.

The [cyan]profile[/] is a profile from "~/.aws/credentials".

[bold]MFA[/]
The attribute [cyan]mfa.device[/] is either the entire ARN for the device, or the part of the ARN after the final slash.

For example, given the ARN:

    "arn:aws:iam::123456789012:mfa/MyDevice"

You may use either "MyDevice" or "arn:aws:iam::123456789012:mfa/MyDevice" as the value for [cyan]mfa.device[/].

[bold]SSM[/]
This plugin can also inject values from SSM Parameter Store into the runtime environment.

You may use the [cyan]path[/] parameter to specify a list of paths to search for within SSM.

Use the [cyan]filter[/] parameter to further filter those results. Possible filters are "startswith", "endswith", and "contains". Prefix the filter with "not" to invert the meaning of the filter.

The optional [cyan]transform[/] parameter specifies a list of text transformations (currently "uppercase", "lowercase", "normalize") to be applied to the name (not the value) before it is injected into the environment. In addition, you may specify a mapping of names to environment variables using the [cyan]rename[/] parameter.

The "normalize" transform replaces non-alphanumeric characters with an underscore. Further, if the first character is numeric, it will be prepended with an underscore. Finally, if the normalized name is empty, a single underscore will be returned.

If a name is specified in [cyan]rename[/], no transformation will be applied; the name will be used as-is.

[cyan]decrypt[/] specifies whether to apply decryption when reading values.

[bold]Notes:[/]
1. If you specify more than one [cyan]path[/], name collisions will result in earlier values being overwritten with later ones.
2. Variables from this plugin will [bold]not[/] overwrite environment variables defined in the main configuration.

[bold]Public methods:[/]
:white_circle:[cyan]plugin:aws.assume_role[/] [bold cyan]role[/]: Assume a role defined in the plugin config. The credentials for assumed roles are not cached and will not be available in other sessions. The plugin must be loaded prior to calling this method.
"""

example = """
plugins:
  aws:
    autoload: true
    profile: default
    username: joe.doe
    account: 123456789012
    region: us-west-2
    mfa:
      device: joes_phone
      expiry: 86400
    roles:
      admin:
        arn: arn:aws:iam::098765432109:role/admin
        expiry: 3600
    ssm:
      decrypt: true
      path:
      - /myproject/dev/
      filter:
      - startswith: DATABASE_
      - not endswith: _URI
      rename:
        DATABASE_USER: DBUSER
        DATABASE_PASSWORD: DBPASS
      transform: [ uppercase, normalize ]

jobs:
  infra/admin:
    help: Enter a shell and assume admin role
    run: ${SHELL}
    interactive: true
    after:
    - plugin:aws.assume_role admin
"""

required_modules: dict[str, str] = {"boto3": "boto3"}
required_binaries: list[str] = []

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import ruamel.yaml as yaml

from lib.boot import missing_modules
from lib.util import ConfigBox, Style, check_permissions, console, get_resolved_path

from plugins import BasePlugin, MetadataType, public

missing: list[str]

if missing := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]AWS[/] disabled, missing modules: {', '.join(missing)}\n")
else:
    import boto3


# ==============================================================================


class Plugin(BasePlugin):
    "Configure AWS credentials."

    key: str = "aws"
    enabled: bool = not missing

    def __get_cache_path(self, config: ConfigBox, env: ConfigBox) -> Path:
        "Return path to cached credentials."

        profile: str = config.get("profile", "default")
        tmpdir: Path = get_resolved_path(config.get("tmp", "/tmp"), env=env)
        cache_file: Path = tmpdir / f"adhd-aws-{profile}.cache"

        return cache_file

    def load(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        """
        If aws configured, prompt for 2fa code, authenticate with AWS, then
        store auth token and temp credentials in cache.
        """

        if not self.enabled:  # we were unable to import module
            self.print(f"support is disabled. Please install boto3 package.", Style.ERROR)
            sys.exit(1)

        plugin_config: ConfigBox = config.plugins[self.key]
        profile: str = plugin_config.get("profile", "default")
        region: str = plugin_config.get("region", "us-east-1")
        mfa: dict[str, Any] = plugin_config.get("mfa", {})
        mfa_device: str | None = mfa.get("device")
        mfa_expiry: int = min(int(mfa.get("expiry", 86400)), 86400)
        cache_file: Path = self.__get_cache_path(plugin_config, env)
        tmpdir: Path = get_resolved_path(plugin_config.get("tmp", "/tmp"), env=env)
        secure_paths: dict[Path, int] = {tmpdir: 0o0700}

        if not check_permissions(secure_paths):
            sys.exit(2)

        if not mfa_device:
            self.print("Missing MFA device.", Style.ERROR)
            sys.exit(2)

        session: boto3.Session = boto3.Session(profile_name=profile)  # type: ignore
        device_arn_prefix: str = f"arn:aws:iam::{plugin_config['account']}:mfa"
        device_arn: str = (
            mfa_device if mfa_device.startswith(device_arn_prefix) else f"{device_arn_prefix}/{mfa_device}"
        )
        token: dict[str, Any] = self.cache_session(
            profile=profile,
            session=session,
            device_arn=device_arn,
            expiry=mfa_expiry,
            cache_file=cache_file,
        )
        response_code: int = token["ResponseMetadata"]["HTTPStatusCode"]

        if response_code != 200:
            self.print(f"Unable to obtain token. Status code {response_code}, exiting.", Style.ERROR)

        credentials = token["Credentials"]

        self.metadata["env"].update(
            {
                "AWS_PROFILE": profile,
                "AWS_DEFAULT_REGION": region,
                "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
                "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
                "AWS_SESSION_TOKEN": credentials["SessionToken"],
                "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
            }
        )

        self.config = plugin_config
        self.profile = profile
        self.region = region

        self.metadata["env"].update(self.get_ssm_values())

        return self.metadata

    def cache_session(
        self,
        profile: str,
        session: boto3.Session,  # type: ignore
        device_arn: str,
        cache_file: Path,
        expiry: int = 86400,
    ) -> dict[str, Any]:
        "Caches session data until expiry, then prompts for new MFA code."

        if not self.enabled:  # we were unable to import module
            self.print("support is disabled. Please install boto3 package.", Style.ERROR)
            sys.exit(1)

        sts: boto3.client.STS = session.client("sts")  # type: ignore

        os.umask(0o0077)  # 0600

        with open(cache_file, "a+") as cached_data:
            data: dict[str, Any] = {}
            prompt: bool = True

            try:
                cached_data.seek(0)
                data = yaml.load(cached_data, Loader=yaml.SafeLoader)
            except:
                prompt = True
            else:
                if data:
                    now: datetime = datetime.utcnow().replace(tzinfo=timezone.utc)
                    expires: datetime = data["Credentials"]["Expiration"].replace(tzinfo=timezone.utc)
                    prompt = now > expires
                else:
                    prompt = True

            if prompt:
                while (
                    len(code := self.prompt(f"Enter MFA code for [bold cyan]{profile}[/]")) != 6
                    or not code.isdigit()
                ):
                    continue

                data = sts.get_session_token(
                    DurationSeconds=expiry,
                    SerialNumber=device_arn,
                    TokenCode=code,
                )

                cached_data.seek(0)
                cached_data.truncate()
                yaml.dump(data, cached_data)

        return data

    def unload(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Remove cached AWS credentials, unset environment."

        cache_file: Path = self.__get_cache_path(config, env)

        if cache_file.exists():
            cache_file.unlink()

        self.metadata["env"].update(
            {
                "AWS_PROFILE": None,
                "AWS_DEFAULT_REGION": None,
                "AWS_ACCESS_KEY_ID": None,
                "AWS_SECRET_ACCESS_KEY": None,
                "AWS_SESSION_TOKEN": None,
                "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": None,
            }
        )

        return self.metadata

    @public(autoload=True)
    def assume_role(self, args: tuple[str, ...], config: ConfigBox, env: ConfigBox) -> MetadataType:
        "Assume a different role."

        session_name: str = args[0]
        roles: dict[str, dict[str, str]] = self.config.get("roles", {})
        role_arn_prefix: str = f"arn:aws:iam::{config['account']}:role"
        role: str | None = roles.get(session_name, {}).get("arn")
        expiry: int = min(int(roles.get(session_name, {}).get("expiry", 43200)), 43200)

        if not self.has_run:
            self.print(" plugin has not been loaded.", Style.ERROR)
            sys.exit(2)

        if not role:
            self.print(f"Incorrect or missing session_name: {session_name}", Style.ERROR)
            sys.exit(2)

        session: boto3.Session = boto3.Session(  # type: ignore
            profile_name=self.profile,
            aws_access_key_id=self.metadata["env"]["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=self.metadata["env"]["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=self.metadata["env"]["AWS_SESSION_TOKEN"],
        )  # type: ignore
        sts: boto3.client.STS = session.client("sts")  # type: ignore
        role_arn: str = role if role.startswith("arn:aws:iam::") else f"{role_arn_prefix}/{role}"

        try:
            assumed_role: dict[str, Any] = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
                DurationSeconds=expiry,
            )
        except Exception as e:
            self.print(f"Unable to assume role: {e}", Style.ERROR)
            sys.exit(2)

        credentials: dict[str, Any] = assumed_role["Credentials"]

        self.metadata["env"].update(
            {
                "AWS_PROFILE": self.profile,
                "AWS_DEFAULT_REGION": self.region,
                "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
                "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
                "AWS_SESSION_TOKEN": credentials["SessionToken"],
                "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
            }
        )

        return self.metadata

    def get_ssm_values(self) -> ConfigBox:
        "Get key/value pairs from SSM Parameter Store and adds them to the environment."

        def normalize(name: str) -> str:
            if name := re.sub(r"[^a-zA-Z_0-9]", "_", name):
                return "_" * name[0].isdigit() + name
            return "_"

        def transform(name: str, transformer: str) -> str:
            _transformers: dict[str, Callable] = {
                "uppercase": str.upper,
                "lowercase": str.lower,
                "normalize": normalize,
            }
            _default: Callable = lambda s: s

            return _transformers.get(transformer, _default)(name)

        def filtered(name: str, filters: dict[str, str]) -> bool:
            "return True if name matches filter"

            _filters: dict[str, Callable] = {
                "startswith": str.startswith,
                "not startswith": lambda name, value: not str.startswith(name, value),
                "endswith": str.endswith,
                "not endswith": lambda name, value: not str.endswith(name, value),
                "contains": lambda name, value: str.find(name, value) >= 0,
                "not contains": lambda name, value: str.find(name, value) < 0,
            }
            _default: Callable = lambda name, value: False

            for _filterer, _value in filters.items():
                if _filters.get(_filterer, _default)(name, _value):
                    return True

            return False

        ssm_config: ConfigBox | None = self.config.get("ssm")

        if not ssm_config:
            return ConfigBox()

        env: ConfigBox = ConfigBox()
        paths: list[str] = ssm_config.get("path", [])
        rename: dict = ssm_config.get("rename", {})
        filters = ssm_config.get("filter", [])
        transformers: list[str] = ssm_config.get("transform", [])
        decrypt: bool = ssm_config.get("decrypt", False)
        session: boto3.Session = boto3.Session(
            profile_name=self.profile,
            region_name=self.metadata["env"]["AWS_DEFAULT_REGION"],
            aws_access_key_id=self.metadata["env"]["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=self.metadata["env"]["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=self.metadata["env"]["AWS_SESSION_TOKEN"],
        )
        ssm: boto3.client.SSM = session.client("ssm")

        for path in paths:
            parameters_page = ssm.get_parameters_by_path(Path=path, Recursive=True, WithDecryption=decrypt)
            parameters_ps = parameters_page["Parameters"]

            while parameters_page.get("NextToken"):
                parameters_page = ssm.get_parameters_by_path(
                    Path=path, Recursive=True, WithDecryption=decrypt, NextToken=parameters_page.get("NextToken")
                )
                parameters_ps += parameters_page["Parameters"]

            parameters_ps = {param["Name"]: param["Value"] for param in parameters_ps}

            for key in parameters_ps:
                name: str = key.split("/")[-1].strip()

                if not any([filtered(name, f) for f in filters]):
                    continue

                if name in rename:
                    name = rename[name]
                else:
                    for transformer in transformers:
                        name = transform(name, transformer)

                env[name] = parameters_ps[key]

            if self.debug:
                if not env:
                    self.print("No matching SSM keys found.", Style.PLUGIN_METHOD_SKIPPED)
                else:
                    self.print("importing SSM params:", Style.PLUGIN_METHOD_SUCCESS)
                    for k, v in env.items():
                        console.print(f"    [green]{k}[/]: [white]${v}[/]", highlight=False)

        return env
