# handler.py - Updated logic to handle S3 events and initiate Transcribe jobs

import os
import json
import uuid  # Used to generate a unique ID for the Transcribe job name
from google import genai
import boto3  # AWS SDK for Python (Transcribe, S3)

# === Environment Variables Loading Block (Local Development Only) ===
try:
    from dotenv import load_dotenv

    # Load environment variables from a local .env file
    load_dotenv()
except ImportError:
    # Pass if dotenv is not available (e.g., running in AWS Lambda environment)
    pass
# ====================================================================

# AWS client setup
s3_client = boto3.client('s3')
# CRITICAL FIX: Explicitly set a supported region (e.g., us-east-1) for Transcribe
# to avoid 'Could not connect to the endpoint URL' errors in unsupported regions.
transcribe_client = boto3.client('transcribe', region_name='us-east-1')

# Retrieve the input bucket name from environment variables
INPUT_BUCKET_NAME = os.environ.get('INPUT_BUCKET_NAME')


def agent_handler(event, context):
    """
    AWS Lambda handler function.
    It processes an S3 upload event and initiates an AWS Transcribe job
    for the uploaded audio file.
    """
    gemini_api_key = os.environ.get("GEMINI_API_KEY")

    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY not found in environment.")
        return {"statusCode": 500, "body": json.dumps("API Key Missing")}

    if not INPUT_BUCKET_NAME:
        print("ERROR: INPUT_BUCKET_NAME not set in environment.")
        return {"statusCode": 500, "body": json.dumps("Bucket name configuration missing.")}

    # 1. Parse the S3 Event (This structure is expected from an S3 trigger)
    try:
        bucket_name = event['Records'][0]['s3']['bucket']['name']
        file_key = event['Records'][0]['s3']['object']['key']
        file_uri = f"s3://{bucket_name}/{file_key}"
        job_name = f"gemini-transcribe-job-{uuid.uuid4()}"

        # --- FIX FOR .m4a and other common formats ---
        format_mapping = {
            'm4a': 'mp4',  # Transcribe expects 'mp4' for m4a files
            'wav': 'wav',
            'mp3': 'mp3',
            'flac': 'flac',
            'ogg': 'ogg'
        }

        # Get file extension and map it
        file_extension = file_key.split('.')[-1].lower()
        media_format = format_mapping.get(file_extension, file_extension)
        # -----------------------------------------------

    except (IndexError, KeyError):
        # Handle cases where the event is not a valid S3 event (e.g., test trigger without full data)
        print("Invalid S3 event structure received. Exiting.")
        return {"statusCode": 202, "body": json.dumps("Not a valid S3 event.")}

    # 2. Start the Transcribe Job
    try:
        response = transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': file_uri},
            MediaFormat=media_format,  # Use the mapped format
            LanguageCode='en-US',  # Use 'he-IL' for Hebrew transcription
            OutputBucketName=INPUT_BUCKET_NAME  # Transcribe writes the output (JSON) to the same bucket
        )

        print(f"Successfully started Transcribe job: {job_name} for file: {file_key}")

        return {
            'statusCode': 200,
            'body': json.dumps({'status': 'Transcription job started', 'job_name': job_name, 'file_key': file_key})
        }

    except Exception as e:
        print(f"Error starting Transcribe job: {e}")
        # Note: This will catch SubscriptionRequiredException if it persists
        return {"statusCode": 500, "body": json.dumps(f"AWS Transcribe Error: {str(e)}")
                }


# --- Local Runner Block (Simulates an S3 Trigger) ---
if __name__ == "__main__":

    # Check if the bucket name is configured before running the local test
    if not INPUT_BUCKET_NAME:
        print("ERROR: Please set INPUT_BUCKET_NAME in your .env file before local testing.")
    else:
        # Create a test event simulating an audio file upload to the S3 bucket
        test_event = {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "s3": {
                        "bucket": {"name": INPUT_BUCKET_NAME},
                        # Use a key that matches the expected file type, e.g., .m4a
                        "object": {"key": "user_recording_123.m4a"}
                    }
                }
            ]
        }

        print("\n--- Running local S3 Trigger Simulation (Transcribe Starter) ---")
        result = agent_handler(event=test_event, context={})

        print("\n--- SIMULATION RESULT ---")
        print(result)
        print("---------------------------\n")