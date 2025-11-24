# presign_handler.py
# Purpose: Provide a public-facing API (via Lambda Function URL or API Gateway)
# that returns a pre-signed S3 URL for direct browser uploads.
# Frontend calls this endpoint, receives an upload URL, and PUTs the file to S3.

import os
import json
import boto3

INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME")
s3_client = boto3.client("s3")


def presign_handler(event, context):
    """
    Lambda entrypoint. Expects POST with JSON: {"fileName": "<name>"}
    Returns: { "uploadUrl": "...", "fileKey": "<name>" }
    """
    if not INPUT_BUCKET_NAME:
        return {"statusCode": 500, "body": json.dumps("ERROR: INPUT_BUCKET_NAME not set.")}

    try:
        body = json.loads(event.get("body", "{}"))
        file_name = body.get("fileName", "uploaded_audio_test.mp3")

        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": INPUT_BUCKET_NAME, "Key": file_name},
            ExpiresIn=3600,
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"uploadUrl": presigned_url, "fileKey": file_name}),
        }
    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
