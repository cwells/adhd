"""
Configure AWS session with MFA.

Session will be cached in [cyan]tmp[/] for [cyan]expiry[/] seconds and you won't be prompted for MFA code until that time, even across multple invokations and multiple shells.

The [cyan]profile[/] is a profile from "~/.aws/credentials".

[bold]MFA[/]
The attribute [cyan]mfa.device[/] is either the entire ARN for the device, or the part of the ARN after the final slash.

For example, given the ARN:

    "arn:aws:iam::123456789012:mfa/MyDevice"

You can use either "MyDevice" or "arn:aws:iam::123456789012:mfa/MyDevice" as the value for [cyan]mfa.device[/].

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

jobs:
  infra/admin:
    help: Enter a shell and assume admin role
    run: ${SHELL}
    interactive: true
    silent: true
    after:
    - plugin:aws.assume_role admin
"""

required_modules: dict[str, str] = {"boto3": "boto3"}
required_binaries: list[str] = []

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml
from lib.boot import missing_modules
from lib.util import ConfigBox, Style, check_permissions, console, get_resolved_path

from plugins import BasePlugin, MetadataType, public

missing: list[str]
boto3: ModuleType | None

if missing := missing_modules(required_modules):
    console.print(f"Plugin [bold blue]AWS[/] disabled, missing modules: {', '.join(missing)}\n")
    boto3 = None
else:
    import boto3


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "aws"
    enabled: bool = boto3 is not None
    has_run: bool = False

    def load(self, config: ConfigBox, env: ConfigBox) -> MetadataType:
        """
        If aws configured, prompt for 2fa code, authenticate with AWS, then
        store auth token and temp credentials in cache.
        """

        if not self.enabled:  # we were unable to import module
            self.print(f"support is disabled. Please install boto3 package.", Style.ERROR)
            sys.exit(1)

        profile: str = config.get("profile", "default")
        region: str = config.get("region", "us-east-1")
        mfa: dict[str, Any] = config.get("mfa", {})
        mfa_device: str | None = mfa.get("device")
        mfa_expiry: int = min(int(mfa.get("expiry", 86400)), 86400)
        tmpdir: Path = get_resolved_path(config.get("tmp", "/tmp"), env=env)
        secure_paths: dict[Path, int] = {tmpdir: 0o0700}

        if not check_permissions(secure_paths):
            sys.exit(2)

        if not mfa_device:
            self.print("Missing MFA device.", Style.ERROR)
            sys.exit(2)

        session: boto3.Session = boto3.Session(profile_name=profile)  # type: ignore
        device_arn_prefix: str = f"arn:aws:iam::{config['account']}:mfa"
        device_arn: str = (
            mfa_device if mfa_device.startswith(device_arn_prefix) else f"{device_arn_prefix}/{mfa_device}"
        )
        token: dict[str, Any] = self.cache_session(
            session=session,
            profile=profile,
            device_arn=device_arn,
            expiry=mfa_expiry,
            tmpdir=tmpdir,
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

        self.config = config
        self.profile = profile
        self.region = region

        return self.metadata

    def cache_session(
        self,
        session: boto3.Session,  # type: ignore
        profile: str,
        device_arn: str,
        expiry: int = 86400,
        tmpdir: Path = Path("/tmp"),
    ) -> dict[str, Any]:
        "Caches session data until expiry, then prompts for new MFA code."

        if not self.enabled:  # we were unable to import module
            self.print("support is disabled. Please install boto3 package.", Style.ERROR)
            sys.exit(1)

        sts: boto3.client.STS = session.client("sts")  # type: ignore
        tmp: Path = Path(tmpdir).expanduser().resolve()
        cache_file: Path = tmp / f"adhd-aws-{profile}.cache"

        os.umask(0o0077)  # 0600

        with open(cache_file, "a+") as cached_data:
            cached_data.seek(0)

            data: dict[str, Any] = yaml.load(cached_data, Loader=yaml.FullLoader)

            if not data or datetime.utcnow().replace(tzinfo=timezone.utc) > data["Credentials"]["Expiration"]:
                while len(code := self.prompt(f"Enter MFA code")) != 6 or not code.isdigit():
                    continue

                data = sts.get_session_token(
                    DurationSeconds=expiry,
                    SerialNumber=device_arn,
                    TokenCode=code,
                )

                cached_data.seek(0)
                cached_data.write(yaml.dump(data))

        return data

    def unload(self, config: ConfigBox, env: ConfigBox) -> None:
        "Remove cached credentials, unset environment."

        profile: str = config.get("profile", "default")
        tmpdir: Path = get_resolved_path(config.get("tmp", "/tmp"), env=env)
        cache_file: Path = tmpdir / f"adhd-aws-{profile}.cache"

        if cache_file.exists():
            cache_file.unlink()

    @public(autoload=True)
    def assume_role(self, args: tuple[str, ...], config: ConfigBox, env: ConfigBox) -> MetadataType:
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
