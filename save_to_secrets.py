#!/usr/bin/env python3
"""
save_to_secrets.py

Deletes an existing secret immediately (ForceDeleteWithoutRecovery=True),
waits until the secret name is free, then creates the new secret.

Usage examples:
$env:AWS_PROFILE = "admin-manager"
python save_to_secrets.py --secrets-file secrets_gemini.json --secret-name my/gemini/all-env --region us-east-1

or
$env:AWS_PROFILE = "admin-manager"
python save_to_secrets.py --env .env --secret-name my/gemini/all-env --region us-east-1 --all

if you want to delete the env profile, you can use the following command:
    Remove-Item Env:AWS_PROFILE

Options:
  --delete-timeout SECONDS   How long to wait for deletion to complete (default 120)
  --quiet                    Minimal output (only success/failure)
  --verbose                  Verbose debug output
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone, timedelta
import logging
import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger("save_to_secrets")

def setup_logging(quiet=False, verbose=False):
    handler = logging.StreamHandler()
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    LOG.setLevel(level)
    handler.setLevel(level)
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    if not LOG.handlers:
        LOG.addHandler(handler)

def read_dotenv(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                env[k] = v
    return env

def secret_exists(client, secret_name):
    try:
        client.describe_secret(SecretId=secret_name)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ResourceNotFoundException", "InvalidRequestException"):
            return False
        raise

def force_delete_secret(client, secret_name):
    try:
        client.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
        LOG.info("delete: issued (force) for %s", secret_name)
        return True
    except ClientError as e:
        msg = str(e)
        code = e.response.get("Error", {}).get("Code", "")
        if code == "InvalidRequestException" and "scheduled for deletion" in msg:
            LOG.info("delete: already scheduled for deletion: %s", secret_name)
            return True
        LOG.error("delete: failed for %s: %s", secret_name, e)
        raise

def wait_until_secret_gone(client, secret_name, timeout_seconds=120, poll_interval=2):
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    while True:
        try:
            client.describe_secret(SecretId=secret_name)
            # still exists
            if datetime.now(timezone.utc) > deadline:
                raise TimeoutError(f"Timed out waiting for secret {secret_name} to be removed (timeout {timeout_seconds}s)")
            LOG.debug("poll: secret still exists, sleeping %ss", poll_interval)
            time.sleep(poll_interval)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ResourceNotFoundException", "InvalidRequestException"):
                LOG.info("delete: confirmed removed: %s", secret_name)
                return
            LOG.error("poll: describe failed: %s", e)
            raise

def create_secret(client, secret_name, secret_string, description=None):
    try:
        client.create_secret(Name=secret_name, SecretString=secret_string, Description=description or "")
        LOG.info("create: success: %s", secret_name)
    except ClientError as e:
        LOG.error("create: failed for %s: %s", secret_name, e)
        raise

def ensure_recreate_secret(client, secret_name, secret_string, description=None, delete_timeout=120):
    try:
        exists = secret_exists(client, secret_name)
    except ClientError as e:
        LOG.error("existence check failed: %s", e)
        raise

    if exists:
        force_delete_secret(client, secret_name)
        wait_until_secret_gone(client, secret_name, timeout_seconds=delete_timeout)
    else:
        LOG.debug("secret does not exist: %s", secret_name)

    try:
        create_secret(client, secret_name, secret_string, description=description)
    except ClientError as e:
        msg = str(e)
        code = e.response.get("Error", {}).get("Code", "")
        if code == "InvalidRequestException" and "scheduled for deletion" in msg:
            LOG.info("create: name reserved, polling until free...")
            wait_until_secret_gone(client, secret_name, timeout_seconds=delete_timeout)
            create_secret(client, secret_name, secret_string, description=description)
        else:
            raise

def build_payload_from_env(env_path, all_keys=False, sensitive_keys="GEMINI_API_KEY"):
    if not os.path.isfile(env_path):
        raise FileNotFoundError(env_path)
    env = read_dotenv(env_path)
    if all_keys:
        return env
    keys = [k.strip() for k in sensitive_keys.split(",") if k.strip()]
    return {k: env[k] for k in keys if k in env}

def main():
    parser = argparse.ArgumentParser(description="Upload .env values to AWS Secrets Manager (force delete existing secret first)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--env", help="Path to .env file (KEY=VALUE)")
    group.add_argument("--secrets-file", help="Path to a JSON file (e.g., secrets_gemini.json) to upload")
    parser.add_argument("--secret-name", required=True, help="Secrets Manager secret name (e.g. my/gemini/credentials)")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--all", action="store_true", help="Store entire .env as JSON (default: only sensitive keys)")
    parser.add_argument("--sensitive-keys", default="GEMINI_API_KEY", help="Comma-separated keys to treat as sensitive (default: GEMINI_API_KEY)")
    parser.add_argument("--delete-timeout", type=int, default=120, help="Seconds to wait for deletion to complete (default 120)")
    parser.add_argument("--quiet", action="store_true", help="Minimal output (warnings/errors only)")
    parser.add_argument("--verbose", action="store_true", help="Verbose debug output")
    args = parser.parse_args()

    setup_logging(quiet=args.quiet, verbose=args.verbose)

    try:
        if args.secrets_file:
            if not os.path.isfile(args.secrets_file):
                LOG.error("secrets file not found: %s", args.secrets_file)
                return
            with open(args.secrets_file, "r", encoding="utf-8") as sf:
                payload = json.load(sf)
        else:
            try:
                payload = build_payload_from_env(args.env, all_keys=args.all, sensitive_keys=args.sensitive_keys)
            except FileNotFoundError:
                LOG.error(".env file not found: %s", args.env)
                return

        if not payload:
            LOG.warning("payload empty — nothing to store")
            return

        secret_string = json.dumps(payload, ensure_ascii=False)
        client = boto3.client("secretsmanager", region_name=args.region)

        ensure_recreate_secret(client, args.secret_name, secret_string, description="Created from .env by save_to_secrets.py", delete_timeout=args.delete_timeout)
        LOG.info("done")
    except Exception as e:
        LOG.error("operation failed: %s", e)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return

if __name__ == "__main__":
    main()
