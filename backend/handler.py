# handler.py
# Serverless Voice Agent: triggered by S3 object creation.
# Flow:
# 1) On audio upload to S3 -> start AWS Transcribe job
# 2) Poll Transcribe job status until completion
# 3) Read Transcribe JSON transcript from S3
# 4) Send transcript to Google Gemini for summary and Q&A
# 5) Write summary and answer back to S3 (next to the original file)

import os
import json
import uuid
import time
import urllib.parse
from typing import Tuple, Optional

import boto3
from botocore.exceptions import ClientError

# Google GenAI (Gemini) SDK
# pip install google-genai (or google-generativeai depending on your chosen SDK)
from google import genai

# --- Environment variables ---
INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "summaries/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro")
TRANSCRIBE_REGION = os.environ.get("TRANSCRIBE_REGION", "us-east-1")
TRANSCRIBE_LANGUAGE = os.environ.get("TRANSCRIBE_LANGUAGE", "en-US")  # use 'he-IL' for Hebrew

# --- AWS clients ---
s3_client = boto3.client("s3")
transcribe_client = boto3.client("transcribe", region_name=TRANSCRIBE_REGION)


def _parse_s3_event(event) -> Tuple[str, str]:
    """Extract bucket and key from the S3 event record."""
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    # S3 may URL-encode the key; decode to get actual key
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
    return bucket, key


def _infer_media_format(key: str) -> str:
    """Map file extension to Transcribe media format."""
    ext = key.split(".")[-1].lower()
    mapping = {
        "m4a": "mp4",  # Transcribe expects 'mp4' for m4a
        "wav": "wav",
        "mp3": "mp3",
        "flac": "flac",
        "ogg": "ogg",
        "mp4": "mp4",
    }
    return mapping.get(ext, ext)


def _start_transcribe_job(bucket: str, key: str) -> str:
    """Start an asynchronous Transcribe job writing output JSON to the same bucket."""
    job_name = f"gemini-transcribe-{uuid.uuid4()}"
    media_uri = f"s3://{bucket}/{key}"
    media_format = _infer_media_format(key)

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": media_uri},
        MediaFormat=media_format,
        LanguageCode=TRANSCRIBE_LANGUAGE,
        OutputBucketName=INPUT_BUCKET_NAME,
    )
    return job_name


def _wait_for_transcribe(job_name: str, timeout_sec: int = 600, poll_sec: int = 5) -> Optional[dict]:
    """
    Poll Transcribe job status until completion or timeout.
    Returns the job dict if completed successfully, else None.
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        resp = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        job = resp["TranscriptionJob"]
        status = job["TranscriptionJobStatus"]
        if status == "COMPLETED":
            return job
        if status == "FAILED":
            raise RuntimeError(f"Transcribe job failed: {job.get('FailureReason')}")
        time.sleep(poll_sec)
    return None


def _read_transcript_from_s3(transcript_uri: str) -> str:
    """
    Transcribe provides a HTTPS URL to the transcript JSON.
    For security and determinism, we prefer reading the JSON from S3
    (the same bucket configured as OutputBucketName).
    """
    # TranscriptUri looks like: https://s3.<region>.amazonaws.com/<bucket>/<key>
    # Extract bucket and key by basic parsing:
    # Alternatively, if OutputBucketName is the same as INPUT_BUCKET_NAME,
    # Transcribe writes a JSON object named {job_name}.json at the root.
    # We will detect that path from the URI.
    parsed = urllib.parse.urlparse(transcript_uri)
    path = parsed.path.lstrip("/")  # "<bucket>/<key>"
    parts = path.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Unexpected transcript URI format: {transcript_uri}")
    bucket, key = parts[0], parts[1]

    obj = s3_client.get_object(Bucket=bucket, Key=key)
    data = obj["Body"].read().decode("utf-8")
    payload = json.loads(data)
    # Transcript JSON schema: {"results": {"transcripts": [{"transcript": "..."}]}}
    transcripts = payload.get("results", {}).get("transcripts", [])
    if not transcripts:
        return ""
    return transcripts[0].get("transcript", "")


def _gemini_summarize_and_answer(text: str, question: str) -> dict:
    """
    Send transcript text to Gemini, asking for:
    - A 5-bullet summary
    - A direct answer to a specific question
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = (
        "You are an expert content analysis assistant.\n"
        "Given the following transcript, provide:\n"
        "1) A concise summary in exactly 5 bullet points.\n"
        "2) A direct answer to the specific question.\n\n"
        "Transcript:\n"
        f"{text}\n\n"
        "Question:\n"
        f"{question}\n"
    )
    # Adjust depending on the SDK interface (e.g., generate_content or models.generate)
    result = client.models.generate(
        model=GEMINI_MODEL,
        input=prompt,
    )
    # Standardize output
    return {
        "summary": result.output_text,  # If your SDK splits parts, adapt accordingly
        "question": question,
    }


def _write_summary_to_s3(original_key: str, summary: dict):
    """
    Write the summary JSON next to the original, under OUTPUT_PREFIX.
    E.g., if original is "audio/user_recording.wav", output becomes "summaries/user_recording.summary.json"
    """
    base_name = original_key.split("/")[-1]
    out_key = f"{OUTPUT_PREFIX}{base_name}.summary.json"
    body = json.dumps(summary, ensure_ascii=False, indent=2)
    s3_client.put_object(
        Bucket=INPUT_BUCKET_NAME,
        Key=out_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    return out_key


def agent_handler(event, context):
    """
    Lambda entrypoint. Handles S3 object creation events:
    - Starts Transcribe
    - Waits for completion
    - Reads transcript
    - Summarizes with Gemini
    - Writes summary JSON to S3
    """
    # Basic validation
    if not GEMINI_API_KEY:
        return {"statusCode": 500, "body": json.dumps("ERROR: GEMINI_API_KEY missing")}
    if not INPUT_BUCKET_NAME:
        return {"statusCode": 500, "body": json.dumps("ERROR: INPUT_BUCKET_NAME missing")}

    try:
        bucket, key = _parse_s3_event(event)
    except (KeyError, IndexError, ValueError) as e:
        return {"statusCode": 202, "body": json.dumps(f"Invalid S3 event: {str(e)}")}

    # Start Transcribe
    try:
        job_name = _start_transcribe_job(bucket, key)
        print(f"Transcribe job started: {job_name} for s3://{bucket}/{key}")
    except ClientError as e:
        return {"statusCode": 500, "body": json.dumps(f"Transcribe start error: {str(e)}")}

    # Wait for completion
    try:
        job = _wait_for_transcribe(job_name)
        if job is None:
            return {"statusCode": 504, "body": json.dumps("Transcribe timed out")}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps(f"Transcribe failed: {str(e)}")}

    # Read transcript
    transcript_uri = job["Transcript"]["TranscriptFileUri"]
    try:
        transcript_text = _read_transcript_from_s3(transcript_uri)
        if not transcript_text.strip():
            return {"statusCode": 200, "body": json.dumps("No transcript text found")}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps(f"Read transcript error: {str(e)}")}

    # Metadata question (optional): read question from object metadata; else default
    question = "What was the meeting objective according to the transcript?"
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
        meta = head.get("Metadata", {})
        if "question" in meta:
            question = meta["question"]
    except Exception:
        pass  # If metadata not accessible, use default

    # Call Gemini
    try:
        summary = _gemini_summarize_and_answer(transcript_text, question)
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps(f"Gemini error: {str(e)}")}

    # Write summary to S3
    try:
        out_key = _write_summary_to_s3(key, summary)
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "ok", "summary_key": out_key}),
        }
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps(f"S3 write error: {str(e)}")}


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