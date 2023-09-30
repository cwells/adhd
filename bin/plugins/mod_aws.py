"""
[bold cyan]Configure AWS session with MFA.[/]

  aws:
    profile: default      # profile name from .aws/credentials
    username: john.doe    # AWS username
    account: 123456789012 # AWS account ID
    region: eu-west-1     # AWS region
    mfa:
      device: MyDevice    # last part of ARN "arn:aws:iam::123456789012:mfa/MyDevice"
      expiry: 86400       # TTL for token (will prompt for MFA code upon expiry)

Session will be cached in [blue]tmp[/] for [blue]expiry[/] seconds and you won't be prompted
for MFA code until that time, even across multple invokations and multiple shells.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from lib.boot import missing_modules
from lib.plugins import BasePlugin, PluginTarget
from lib.util import ConfigBox, Style, check_permissions, console, get_resolved_path

if missing_modules(["boto3"]):
    print("boto3 not found: AWS support disabled.")
    boto3 = None
else:
    import boto3


# ==============================================================================


class Plugin(BasePlugin):
    key: str = "aws"
    enabled: bool = boto3 is not None
    target: PluginTarget = PluginTarget.ENV
    has_run: bool = False

    def load(self, config: ConfigBox, env: dict[str, Any]) -> dict[str, str]:
        """
        If aws configured, prompt for 2fa code, authenticate with AWS, then
        store auth token and temp credentials in cache.
        """

        if not self.enabled:  # we were unable to import module
            console.print(f"{Style.ERROR}AWS support is disabled. Please install boto3 package.")
            sys.exit(1)

        profile: str = config.get("profile", "default")
        region: str = config.get("region", "us-east-1")
        mfa: dict[str, Any] = config.get("mfa", {})
        mfa_device: str | None = mfa.get("device")
        mfa_expiry: int = int(mfa.get("expiry", 86400))
        tmpdir: Path = get_resolved_path(config.get("tmp", "/tmp"), env=env)
        secure_paths: dict[Path, int] = {tmpdir: 0o0700}

        if not check_permissions(secure_paths):
            sys.exit(2)

        if not mfa_device:
            console.print(f"{Style.ERROR}Missing MFA device.")
            sys.exit(2)

        session: boto3.Session = boto3.Session(profile_name=profile)  # type: ignore
        device_arn: str = f"arn:aws:iam::{config['account']}:mfa/{mfa_device}"
        token: dict[str, Any] = self.cache_session(
            session=session,
            profile=profile,
            device_arn=device_arn,
            expiry=mfa_expiry,
            tmpdir=tmpdir,
        )
        response_code: int = token["ResponseMetadata"]["HTTPStatusCode"]

        if response_code != 200:
            console.print(f"{Style.ERROR}Unable to obtain token. Status code {response_code}, exiting.")

        credentials = token["Credentials"]

        return {
            "AWS_PROFILE": profile,
            "AWS_DEFAULT_REGION": region,
            "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
            "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
            "AWS_SESSION_TOKEN": credentials["SessionToken"],
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
        }

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
            console.print(f"{Style.ERROR}AWS support is disabled. Please install boto3 package.")
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

    def unload(self, config: ConfigBox, env: dict[str, Any]) -> list[str]:
        "Remove cached credentials, unset environment."

        profile: str = config.get("profile", "default")
        tmpdir: Path = get_resolved_path(config.get("tmp", "/tmp"), env=env)
        cache_file: Path = tmpdir / f"adhd-aws-{profile}.cache"

        if cache_file.exists():
            cache_file.unlink()

        return [  # these will be removed from env
            "AWS_PROFILE",
            "AWS_DEFAULT_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS",
        ]
