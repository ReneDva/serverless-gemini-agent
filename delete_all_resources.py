#!/usr/bin/env python3
# delete_all_resources.py
# usage examples:
# python delete_all_resources.py --profile admin-manager --region us-east-1
# python delete_all_resources.py --role-arn arn:aws:iam::123456789012:role/AdminRole

import argparse
import boto3
import botocore
from botocore.exceptions import ClientError, NoRegionError

REGION_DEFAULT = "us-east-1"

BUCKETS = [
    "rene-gemini-agent-user-input-2025",
    "rene-sam-artifacts-bucket",
]

STACK_NAMES = [
    "rene-gemini-agent-stack-dev",
    "aws-sam-cli-managed-default",
]


def create_session(region, profile=None, role_arn=None, role_session_name="admin-session"):
    if profile and role_arn:
        base_session = boto3.Session(profile_name=profile, region_name=region)
        sts = base_session.client("sts")
        resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=role_session_name)
        creds = resp["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

    if profile:
        return boto3.Session(profile_name=profile, region_name=region)

    if role_arn:
        base_session = boto3.Session(region_name=region)
        sts = base_session.client("sts")
        resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=role_session_name)
        creds = resp["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

    return boto3.Session(region_name=region)


def bucket_exists(s3, bucket):
    try:
        s3.head_bucket(Bucket=bucket)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        print(f"ℹ️ Bucket '{bucket}' not accessible: {code}. Skipping.")
        return False


def empty_bucket(s3, bucket):
    print(f"\n🔄 Emptying bucket: {bucket}")

    if not bucket_exists(s3, bucket):
        return

    try:
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Suspended"})
    except ClientError as e:
        print(f"⚠️ Could not suspend versioning for '{bucket}': {e}")

    paginator = s3.get_paginator("list_object_versions")
    try:
        pages = paginator.paginate(Bucket=bucket)
    except ClientError as e:
        print(f"❌ Failed to paginate object versions in '{bucket}': {e}")
        return

    batch = []
    for page in pages:
        for v in page.get("Versions", []):
            batch.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for m in page.get("DeleteMarkers", []):
            batch.append({"Key": m["Key"], "VersionId": m["VersionId"]})

        while len(batch) >= 1000:
            chunk = {"Objects": batch[:1000], "Quiet": True}
            try:
                resp = s3.delete_objects(Bucket=bucket, Delete=chunk)
                print(f"✅ Deleted {len(resp.get('Deleted', []))} versions/markers; Errors: {resp.get('Errors', [])}")
            except ClientError as e:
                print(f"❌ delete_objects chunk failed: {e}")
            batch = batch[1000:]

    if batch:
        try:
            resp = s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            print(f"✅ Deleted final {len(resp.get('Deleted', []))} versions/markers; Errors: {resp.get('Errors', [])}")
        except ClientError as e:
            print(f"❌ delete_objects final batch failed: {e}")

    # נרוקן גם אובייקטים רגילים (non-versioned)
    try:
        obj_paginator = s3.get_paginator("list_objects_v2")
        obj_pages = obj_paginator.paginate(Bucket=bucket)
        keys = []
        for p in obj_pages:
            for o in p.get("Contents", []):
                keys.append({"Key": o["Key"]})
        if keys:
            print(f"🧹 Deleting {len(keys)} current objects (non-versioned).")
            for i in range(0, len(keys), 1000):
                chunk = {"Objects": keys[i : i + 1000], "Quiet": True}
                try:
                    resp = s3.delete_objects(Bucket=bucket, Delete=chunk)
                    print(f"✅ Deleted {len(resp.get('Deleted', []))} current objects; Errors: {resp.get('Errors', [])}")
                except ClientError as e:
                    print(f"❌ delete_objects (current objects) failed: {e}")
    except ClientError as e:
        print(f"ℹ️ list_objects_v2 info: {e}")

    # בדיקה אחרונה
    try:
        final = s3.list_object_versions(Bucket=bucket)
        v_left = len(final.get("Versions", []))
        m_left = len(final.get("DeleteMarkers", []))
        print(f"🔎 Remaining Versions: {v_left}, DeleteMarkers: {m_left}")
    except ClientError as e:
        print(f"ℹ️ list_object_versions final check failed: {e}")


def delete_bucket(s3, bucket):
    print(f"🗑️ Deleting bucket: {bucket}")

    if not bucket_exists(s3, bucket):
        return

    try:
        s3.delete_bucket(Bucket=bucket)
        print(f"✅ Bucket '{bucket}' delete initiated.")
    except ClientError as e:
        print(f"❌ Failed to delete bucket '{bucket}': {e}")
        try:
            empty_bucket(s3, bucket)
            s3.delete_bucket(Bucket=bucket)
            print(f"✅ Bucket '{bucket}' delete retried and initiated.")
        except ClientError as e2:
            print(f"❌ Retry delete bucket '{bucket}' failed: {e2}")


def stack_exists(cf, stack_name):
    try:
        resp = cf.describe_stacks(StackName=stack_name)
        return True if resp.get("Stacks") else False
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ValidationError":
            print(f"ℹ️ Stack '{stack_name}' does not exist. Skipping stack deletion.")
            return False
        print(f"ℹ️ Could not describe stack '{stack_name}': {e}. Skipping.")
        return False


def disable_termination_protection_if_enabled(cf, stack_name):
    try:
        resp = cf.describe_stacks(StackName=stack_name)
        stacks = resp.get("Stacks", [])
        if not stacks:
            return
        stack = stacks[0]
        tp = stack.get("EnableTerminationProtection", False)
        if tp:
            print(f"🔐 Termination protection is enabled for '{stack_name}', disabling it.")
            cf.update_termination_protection(StackName=stack_name, EnableTerminationProtection=False)
            # אין waiter רשמי; נחכה מעט כדי לאפשר שינוי להתעדכן
            import time
            time.sleep(3)
    except ClientError as e:
        print(f"⚠️ Could not check/disable termination protection for '{stack_name}': {e}")


def delete_stack(cf, stack_name):
    print(f"\n🧨 Deleting CloudFormation stack: {stack_name}")
    if not stack_exists(cf, stack_name):
        return
    disable_termination_protection_if_enabled(cf, stack_name)
    try:
        cf.delete_stack(StackName=stack_name)
        print(f"✅ Stack delete initiated for '{stack_name}'. Waiting for completion...")
        waiter = cf.get_waiter("stack_delete_complete")
        waiter.wait(StackName=stack_name)
        print(f"🎉 Stack '{stack_name}' deleted.")
    except ClientError as e:
        print(f"❌ Failed to delete stack '{stack_name}': {e}")
    except Exception as e:
        print(f"❌ Unexpected error waiting for stack delete: {e}")


def main():
    parser = argparse.ArgumentParser(description="Empty and delete S3 buckets and CloudFormation stacks.")
    parser.add_argument("--region", default=REGION_DEFAULT, help="AWS region (default: us-east-1)")
    parser.add_argument("--profile", help="AWS CLI profile name to use")
    parser.add_argument("--role-arn", help="ARN of role to assume (optional)")
    parser.add_argument("--role-session-name", default="admin-session", help="Role session name for STS assume_role")
    args = parser.parse_args()

    try:
        session = create_session(region=args.region, profile=args.profile, role_arn=args.role_arn, role_session_name=args.role_session_name)
        s3 = session.client("s3")
        cf = session.client("cloudformation")
    except NoRegionError:
        raise RuntimeError("Region must be specified. Set REGION or AWS_DEFAULT_REGION.")

    for b in BUCKETS:
        if bucket_exists(s3, b):
            empty_bucket(s3, b)
            delete_bucket(s3, b)
        else:
            print(f"⏭️ Skipping bucket '{b}' because it does not exist or is not accessible.")

    for stack in STACK_NAMES:
        delete_stack(cf, stack)


if __name__ == "__main__":
    main()
