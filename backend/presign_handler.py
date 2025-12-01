# presign_handler.py
import os
import json
import boto3

INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME")
s3_client = boto3.client("s3", region_name="us-east-1")

def presign_handler(event, context):
    """
    Lambda entrypoint.
    - OPTIONS: מחזיר תשובת preflight עם כותרות CORS
    - POST: מצפה ל־JSON {"fileName": "<name>"} ומחזיר כתובת presigned
    """
    method = event.get("requestContext", {}).get("http", {}).get("method", "")

    # טיפול בבקשת OPTIONS (preflight)
    if method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": ""
        }

    # טיפול בבקשת POST
    if not INPUT_BUCKET_NAME:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps("ERROR: INPUT_BUCKET_NAME not set.")
        }

    try:
        body = json.loads(event.get("body") or "{}")
        file_name = body.get("fileName", "uploaded_audio_test.mp3")

        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": INPUT_BUCKET_NAME, "Key": file_name},
            ExpiresIn=3600,
        )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({"uploadUrl": presigned_url, "fileKey": file_name}),
        }
    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)})
        }
