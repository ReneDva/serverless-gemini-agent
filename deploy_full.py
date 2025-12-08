# cd C:\serverless-gemini-agent
# .\.venv\Scripts\Activate.ps1
# py deploy_full.py --profile admin-manager --region us-east-1
#!/usr/bin/env python3
"""
deploy_full.py

Automates:
  1. Verify required S3 buckets exist (artifacts + frontend).
  2. Run `sam build` and `sam deploy` (parameters read from samconfig.toml).
  3. Fetch CloudFormation stack outputs.
  4. Patch frontend/upload.js with API endpoint URLs.
  5. Upload frontend files to S3 and configure bucket as a static website.
  6. Print the public website URL.

Usage examples:
  py deploy_full.py --profile admin-manager --region us-east-1
  py deploy_full.py --role-arn arn:aws:iam::123456789012:role/AdminRole
"""
import time
import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path
import json
import boto3
import toml
from botocore.exceptions import ClientError

# ---------- Local-only defaults ----------
FRONTEND_DIR: str = "frontend"
UPLOAD_JS_PATH: Path = os.path.join(FRONTEND_DIR, "upload.js")
PREFIX: str = "frontend/"
SAMCONFIG_PATH: str = "samconfig.toml"
# ----------------------------------------


def run_cmd(cmd):
    """Run a shell command and print it."""
    print(">", " ".join(cmd))
    subprocess.check_call(" ".join(cmd), shell=True)


def create_session(region, profile=None, role_arn=None, role_session_name="deploy-session"):
    """Create a boto3 session, supporting profile or assume-role."""
    if profile and role_arn:
        base = boto3.Session(profile_name=profile, region_name=region)
        sts = base.client("sts")
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
        base = boto3.Session(region_name=region)
        sts = base.client("sts")
        resp = sts.assume_role(RoleArn=role_arn, RoleSessionName=role_session_name)
        creds = resp["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
    return boto3.Session(region_name=region)


def recreate_bucket(s3_client, bucket, region):
    """Force delete bucket if exists, then create it again."""
    # מחיקה אם קיים
    try:
        s3_client.head_bucket(Bucket=bucket)
        print(f"Bucket {bucket} exists. Deleting...")
        # מחיקת כל האובייקטים
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                s3_client.delete_object(Bucket=bucket, Key=obj["Key"])
        # מחיקת הדלי עצמו
        s3_client.delete_bucket(Bucket=bucket)
        waiter = s3_client.get_waiter("bucket_not_exists")
        waiter.wait(Bucket=bucket)
        print(f"Bucket {bucket} deleted.")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            print(f"Bucket {bucket} does not exist, will create new.")
        else:
            raise

    # יצירה מחדש
    print(f"Creating bucket {bucket} in region {region}...")
    if region == "us-east-1":
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region}
        )
    print(f"Bucket {bucket} created.")


def delete_stack_if_exists(cf_client, stack_name):
    """Check if stack exists; if so, delete it and wait for deletion."""
    try:
        resp = cf_client.describe_stacks(StackName=stack_name)
        status = resp["Stacks"][0]["StackStatus"]
        print(f"Stack {stack_name} exists with status {status}. Deleting...")
        cf_client.delete_stack(StackName=stack_name)

        waiter = cf_client.get_waiter("stack_delete_complete")
        waiter.wait(StackName=stack_name)
        print(f"Stack {stack_name} deleted successfully.")
    except ClientError as e:
        if "does not exist" in str(e):
            print(f"Stack {stack_name} does not exist, continuing...")
        else:
            raise


def check_iam_permissions(session):
    """Verify IAM permissions for CloudFormation and S3 by making simple API calls."""
    try:
        cf = session.client("cloudformation")
        s3 = session.client("s3")
        cf.describe_stacks()
        s3.list_buckets()
        print("IAM permissions check passed: able to call CloudFormation and S3 APIs.")
    except ClientError as e:
        print("IAM permissions check failed:", e)
        sys.exit(1)


def sam_build_and_deploy(profile=None):
    """Run SAM validate, build and deploy, relying on samconfig.toml for parameters."""
    try:
        run_cmd(["sam", "validate", "--lint"])
    except subprocess.CalledProcessError:
        print("SAM lint warnings detected, continuing anyway...")
    run_cmd(["sam", "build"])
    deploy_cmd = ["sam", "deploy", "--no-confirm-changeset"]
    if profile:
        deploy_cmd.extend(["--profile", profile])
        print("Using profile:", profile)
    else:
        print("Using default profile from samconfig.toml or AWS CLI")
    run_cmd(deploy_cmd)


def log_stack_events(cf_client, stack_name):
    """Print recent CloudFormation events for debugging."""
    try:
        resp = cf_client.describe_stack_events(StackName=stack_name)
        events = resp.get("StackEvents", [])
        print("Recent CloudFormation events:")
        for e in events[:10]:
            print(f"{e['Timestamp']} - {e['LogicalResourceId']} - {e['ResourceStatus']} - {e.get('ResourceStatusReason','')}")
    except ClientError as e:
        print("Could not fetch stack events:", e)


def get_stack_outputs(cf_client, stack_name):
    """Fetch CloudFormation stack outputs as a dict."""
    try:
        resp = cf_client.describe_stacks(StackName=stack_name)
    except ClientError as e:
        print("Could not describe stack:", e)
        return {}
    stacks = resp.get("Stacks", [])
    if not stacks:
        return {}
    outputs = stacks[0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}

def create_base_prefixes(s3_client, bucket):
    """Create base prefixes (recordings/, summaries/, transcriptions/) as empty objects."""
    prefixes = ["recordings/", "summaries/", "transcriptions/"]
    for p in prefixes:
        key = p  # S3 "folder" key
        try:
            s3_client.put_object(Bucket=bucket, Key=key)
            print(f"Created base prefix: s3://{bucket}/{key}")
        except ClientError as e:
            print(f"Failed to create prefix {key}: {e}")

def check_bucket_notifications(s3_client, bucket):
    conf = s3_client.get_bucket_notification_configuration(Bucket=bucket)
    print("Bucket notification configuration:", json.dumps(conf, indent=2))
    # אפשר להוסיף לוגיקה שבודקת שיש prefix recordings/


def patch_upload_js(upload_js_path, presign_url, summary_url, backup=True):
    """Replace PRESIGN_ENDPOINT and SUMMARY_ENDPOINT in upload.js with stack URLs."""
    if not os.path.isfile(upload_js_path):
        print("upload.js not found at", upload_js_path)
        return False

    with open(upload_js_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith("const PRESIGN_ENDPOINT"):
            new_lines.append(
                f'const PRESIGN_ENDPOINT = isLocal ? "http://127.0.0.1:3000/presign" : "{presign_url}";\n'
            )
        elif line.strip().startswith("const SUMMARY_ENDPOINT"):
            new_lines.append(
                f'const SUMMARY_ENDPOINT = isLocal ? "http://127.0.0.1:3000/summary" : "{summary_url}";\n'
            )
        else:
            new_lines.append(line)

    if backup:
        bak = upload_js_path + ".bak"
        shutil.copy2(upload_js_path, bak)
        print("Backup created:", bak)

    with open(upload_js_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("upload.js patched successfully.")
    return True


def upload_frontend(s3_client, bucket, frontend_dir, prefix="frontend/"):
    """
    Upload only selected frontend files to an existing S3 bucket.

    Behavior:
      - Uploads only: index.html, upload.js, font-loader.js, redirect-index.html.
      - Special case: if redirect-index.html exists, it is uploaded
        directly to the bucket root as index.html (for S3 website hosting).
      - Other files are ignored.
      - Each file is uploaded with appropriate ContentType.

    Args:
        s3_client: boto3 S3 client.
        bucket (str): Target S3 bucket name.
        frontend_dir (str): Local directory containing frontend files.
        prefix (str): Prefix inside the bucket for frontend files (default "frontend/").

    Returns:
        bool: True if upload succeeded, False otherwise.
    """
    if not os.path.isdir(frontend_dir):
        print("Frontend directory not found:", frontend_dir)
        return False

    allowed_files = {"index.html", "upload.js", "font-loader.js", "redirect-index.html"}
    uploaded = []

    for fname in allowed_files:
        local_path = os.path.join(frontend_dir, fname)
        if not os.path.isfile(local_path):
            continue

        # Special case: redirect-index.html -> bucket root as index.html
        if fname == "redirect-index.html":
            s3_key = "index.html"
        else:
            s3_key = prefix + fname

        print(f"Uploading {local_path} -> s3://{bucket}/{s3_key}")
        s3_client.upload_file(
            local_path,
            bucket,
            s3_key,
            ExtraArgs={"ContentType": guess_content_type(fname)},
        )
        uploaded.append(s3_key)

    print(f"Uploaded {len(uploaded)} files: {uploaded}")
    return True


def guess_content_type(filename):
    """Guess MIME type based on file extension."""
    import mimetypes
    ctype, _ = mimetypes.guess_type(filename)
    return ctype or "binary/octet-stream"


def configure_bucket_website_and_policy(s3_client, bucket, prefix="frontend/"):
    """Configure S3 bucket as static website and apply public-read policy."""
    website_conf = {
        "IndexDocument": {"Suffix": "index.html"},
        "ErrorDocument": {"Key": "index.html"},
    }
    try:
        s3_client.put_bucket_website(Bucket=bucket, WebsiteConfiguration=website_conf)
        print("Bucket website configuration set.")
    except ClientError as e:
        print("Failed to set website configuration:", e)

    try:
        s3_client.delete_public_access_block(Bucket=bucket)
        print("Removed public access block (if existed).")
    except ClientError:
        pass

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowPublicReadForFrontend",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": [
                    f"arn:aws:s3:::{bucket}/{prefix}*",
                    f"arn:aws:s3:::{bucket}/index.html",
                    f"arn:aws:s3:::{bucket}/redirect-index.html",
                ],
            }
        ],
    }
    try:
        s3_client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        print("Bucket policy applied for public read on frontend files.")
    except ClientError as e:
        print("Failed to put bucket policy:", e)


def get_bucket_website_url(s3_client, bucket):
    """Return the website endpoint URL for the bucket."""
    try:
        resp = s3_client.get_bucket_location(Bucket=bucket)
        region = resp.get("LocationConstraint") or "us-east-1"
        if region == "us-east-1":
            return f"http://{bucket}.s3-website-us-east-1.amazonaws.com"
        else:
            return f"http://{bucket}.s3-website.{region}.amazonaws.com"
    except ClientError as e:
        print("Could not get bucket location:", e)
        return None


def get_values_from_samconfig(path=SAMCONFIG_PATH):
    """Parse samconfig.toml and return key values."""
    cfg = toml.load(path)
    deploy_params = cfg["default"]["deploy"]["parameters"]
    stack_name = deploy_params["stack_name"]
    artifacts_bucket = deploy_params["s3_bucket"]
    region = deploy_params["region"]
    return stack_name, artifacts_bucket, region

def main():
    """
    Main deployment workflow:
      1. Parse CLI arguments (region, profile, role, frontend directory, etc.).
      2. Load stack name, artifacts bucket, and region from samconfig.toml.
      3. Extract InputBucketName from parameter_overrides in samconfig.toml.
      4. Create a boto3 session using profile or role.
      5. Verify IAM permissions for CloudFormation and S3.
      6. Delete the stack if it already exists (clean redeploy).
      7. Recreate the artifacts bucket (temporary bucket for SAM packaging).
      8. Run SAM build and deploy.
      9. Fetch stack outputs (API endpoints).
     10. Patch upload.js with the API endpoints.
     11. Upload frontend files into the InputBucket under the given prefix.
     12. Configure InputBucket as a static website and apply public-read policy.
     13. Print the website endpoint URL.
    """
    # --- שלב מקדים: מחיקת כל המשאבים הקיימים ---
    try:
        print("🧨 Running cleanup script before deploy...")
        subprocess.check_call([
            sys.executable,  # מריץ עם אותו Python שבו הסקריפט רץ
            "delete_all_resources.py",
            "--profile", "admin-manager",
            "--region", "us-east-1"
        ])
        print("✅ Cleanup completed.")
    except subprocess.CalledProcessError as e:
        print("⚠️ Cleanup script failed:", e)
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Build & deploy SAM, patch frontend, upload and configure S3 website."
    )
    parser.add_argument("--region", help="AWS region (overrides samconfig.toml)")
    parser.add_argument("--profile", help="AWS CLI profile name")
    parser.add_argument("--role-arn", help="ARN of role to assume (optional)")
    parser.add_argument("--frontend-dir", default=FRONTEND_DIR)
    parser.add_argument("--upload-js", default=UPLOAD_JS_PATH)
    parser.add_argument("--prefix", default=PREFIX)
    args = parser.parse_args()

    # --- Load values from samconfig.toml ---
    stack_name, artifacts_bucket, region_from_config = get_values_from_samconfig(SAMCONFIG_PATH)
    region = args.region or region_from_config

    # Extract InputBucketName from parameter_overrides
    input_bucket = None
    cfg = toml.load(SAMCONFIG_PATH)
    param_overrides = cfg["default"]["deploy"]["parameters"].get("parameter_overrides", "")
    for part in param_overrides.split():
        if part.startswith("InputBucketName="):
            input_bucket = part.split("=")[1].strip('"')

    if not input_bucket:
        print("Input bucket name not found in samconfig.toml parameter_overrides.")
        sys.exit(1)

    # --- Create boto3 session ---
    session = create_session(region=region, profile=args.profile, role_arn=args.role_arn)
    s3 = session.client("s3")
    cf = session.client("cloudformation")

    # Verify IAM permissions
    check_iam_permissions(session)

    # Force delete stack if it already exists (clean redeploy)
    delete_stack_if_exists(cf, stack_name)

    # 1) Recreate artifacts bucket and run SAM build/deploy
    try:
        recreate_bucket(s3, artifacts_bucket, region)
        sam_build_and_deploy(args.profile)
    except subprocess.CalledProcessError as e:
        print("SAM build/deploy failed:", e)
        log_stack_events(cf, stack_name)
        sys.exit(1)

    # 2) Get stack outputs
    outputs = get_stack_outputs(cf, stack_name)
    print("Stack outputs:", outputs)

    # 2b) Create base prefixes in input bucket
    create_base_prefixes(s3, input_bucket)
    check_bucket_notifications(s3, input_bucket)

    # 3) Patch upload.js with API endpoints
    presign_url = outputs.get("UploadApiUrl")
    summary_url = outputs.get("SummaryApiUrl")

    if presign_url and summary_url:
        patch_upload_js(args.upload_js, presign_url, summary_url)
    else:
        print("Missing PresignApiUrl or SummaryApiUrl in stack outputs")

    # 4) Upload frontend files into InputBucket under prefix
    if not upload_frontend(s3, input_bucket, args.frontend_dir, prefix=args.prefix):
        print("Frontend upload failed.")
        sys.exit(1)

    # 5) Configure InputBucket as static website and apply public-read policy
    configure_bucket_website_and_policy(s3, input_bucket, prefix=args.prefix)

    # 6) Print website URL (only after website configuration is set)
    website_url = get_bucket_website_url(s3, input_bucket)
    if website_url:
        print("Frontend website URL:", website_url)

    print("Deployment complete. Frontend should be available via S3 website endpoint or CloudFront if configured.")

    # 7) Invoke Lambda once to ensure log group exists
    lambda_client = session.client("lambda")
    voice_fn_arn = outputs.get("VoiceAgentFunctionArn")
    if voice_fn_arn:
        print("Invoking Lambda once to create log group...")
        try:
            resp = lambda_client.invoke(
                FunctionName=voice_fn_arn,
                InvocationType="RequestResponse",  # מחכה לתוצאה
                Payload=json.dumps({
                      "Records": [
                        {
                          "s3": {
                            "bucket": {"name": "rene-gemini-agent-user-input-2025"},
                            "object": {"key": "recordings/user_recording_123.m4a"}
                          }
                        }
                      ]
                    }
                ).encode("utf-8")
                            )
            print("Test invoke sent, status:", resp.get("StatusCode"))
        except ClientError as e:
            print("Failed to invoke Lambda:", e)

        # המתנה קצרה כדי לאפשר ל־CloudWatch ליצור את הלוג־גרופ

        time.sleep(5)

        # 8) Tail logs live
        log_group_name = f"/aws/lambda/{voice_fn_arn.split(':')[-1]}"
        print(f"Starting live log tail for {log_group_name}...")
        subprocess.Popen([
            "aws", "logs", "tail", log_group_name,
            "--follow", "--region", region,
            "--profile", args.profile or "default"
        ])


if __name__ == "__main__":
    main()
