# tests/local_runner.py
"""
Local runner for Serverless Gemini Agent
- Mock mode (default): uses in-memory mocks for S3, Transcribe, Gemini
- Real cloud mode: upload a local audio file to S3 and optionally invoke deployed Lambda,
  or wait for the summary file to appear in S3 (polling).
Usage:
  # Mock run (default)
  python tests/local_runner.py

  # Real cloud run (upload local file and wait for summary)
  REAL_CLOUD=true AUDIO_PATH=/path/to/audio.wav python tests/local_runner.py

  # Real cloud run and invoke Lambda directly after upload
  REAL_CLOUD=true AUDIO_PATH=/path/to/audio.wav INVOKE_LAMBDA=true LAMBDA_NAME=my-deployed-lambda python tests/local_runner.py
"""

import os
import json
import time
import urllib.parse
import sys

from unittest import mock
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")


# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Import modules under test (these are your backend handlers)
try:
    from backend import handler as voice_handler_module
    from backend import presign_handler as presign_module
except Exception as e:
    print("ERROR: Could not import backend modules. Check project structure.")
    raise
# config.py (recommended: separate file)
import os
from pathlib import Path

# --- Helper conversions ---
def str_to_bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y")

# --- Environment / configuration with safe defaults ---
INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME", "rene-gemini-agent-user-input-2025")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "DUMMY_KEY_FOR_LOCAL_TESTS")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "summaries/")
TRANSCRIBE_REGION = os.environ.get("TRANSCRIBE_REGION", "us-east-1")

# Flags (env override, otherwise default values here)
# Default: development uses mocks (REAL_CLOUD=False). Change to True for real cloud runs.
REAL_CLOUD = str_to_bool(os.environ.get("REAL_CLOUD"), default=False)

# AUDIO_PATH can be provided via env or hardcoded here for convenience in local testing.
# Use Path for cross-platform handling and validate existence when REAL_CLOUD=True.
AUDIO_PATH_ENV = os.environ.get("AUDIO_PATH", "")
AUDIO_PATH = Path(AUDIO_PATH_ENV) if AUDIO_PATH_ENV else None

# Optionally hardcode a path for quick local runs (comment out in production)
# AUDIO_PATH = Path(r"C:\Users\rened\OneDrive\מסמכים\Agent_project_gemmini\user_recording_123.m4a")

INVOKE_LAMBDA = str_to_bool(os.environ.get("INVOKE_LAMBDA"), default=False)
LAMBDA_NAME = os.environ.get("LAMBDA_NAME", None)

SUMMARY_POLL_TIMEOUT = int(os.environ.get("SUMMARY_POLL_TIMEOUT", "300"))
SUMMARY_POLL_INTERVAL = int(os.environ.get("SUMMARY_POLL_INTERVAL", "5"))

# --- Validation helper (call before real-cloud flow) ---
def validate_real_cloud_config():
    if REAL_CLOUD:
        if not AUDIO_PATH:
            raise ValueError("REAL_CLOUD is True but AUDIO_PATH is not set. Set AUDIO_PATH env var or update .env.")
        if not AUDIO_PATH.exists() or not AUDIO_PATH.is_file():
            raise FileNotFoundError(f"AUDIO_PATH not found: {AUDIO_PATH}\n"
                                    "Check that the path is correct, accessible, and that you run the script in the same shell where the env var is set.")
        if not INPUT_BUCKET_NAME:
            raise ValueError("INPUT_BUCKET_NAME must be set for REAL_CLOUD runs.")


# --- Sample transcript JSON used by mocks ---
SAMPLE_TRANSCRIBE_JSON = {
    "results": {
        "transcripts": [
            {"transcript": "This is a sample transcript text produced for local testing. The meeting objective was to plan the Q1 roadmap."}
        ]
    }
}


# --- Mock implementations for boto3 clients (same as before) ---
class MockBody:
    def __init__(self, data_bytes):
        self._data = data_bytes

    def read(self):
        return self._data


class MockS3Client:
    def __init__(self, bucket_name):
        self.bucket = bucket_name
        self.storage = {}  # in-memory store for put_object calls

    def get_object(self, Bucket, Key):
        if Key.endswith(".json"):
            body = json.dumps(SAMPLE_TRANSCRIBE_JSON).encode("utf-8")
            return {"Body": MockBody(body)}
        if Key.endswith(".m4a") or Key.endswith(".mp3") or Key.endswith(".wav"):
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}
        if Key in self.storage:
            return {"Body": MockBody(self.storage[Key].encode("utf-8"))}
        raise FileNotFoundError(f"MockS3Client: Key not found: {Key}")

    def put_object(self, Bucket, Key, Body, ContentType="application/json"):
        self.storage[Key] = Body.decode("utf-8") if isinstance(Body, (bytes, bytearray)) else str(Body)
        print(f"[MockS3] put_object -> Bucket: {Bucket}, Key: {Key}, ContentType: {ContentType}")
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def head_object(self, Bucket, Key):
        return {"Metadata": {}}

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn=3600):
        bucket = Params.get("Bucket")
        key = Params.get("Key")
        return f"https://mock-s3/{bucket}/{urllib.parse.quote(key)}?expires_in={ExpiresIn}"


class MockTranscribeClient:
    def __init__(self, transcript_key):
        self.transcript_key = transcript_key
        self.started_jobs = {}

    def start_transcription_job(self, TranscriptionJobName, Media, MediaFormat, LanguageCode, OutputBucketName):
        transcript_uri = f"https://s3.amazonaws.com/{OutputBucketName}/{self.transcript_key}.json"
        job = {
            "TranscriptionJobName": TranscriptionJobName,
            "Media": Media,
            "MediaFormat": MediaFormat,
            "LanguageCode": LanguageCode,
            "OutputBucketName": OutputBucketName,
            "TranscriptionJobStatus": "COMPLETED",
            "Transcript": {"TranscriptFileUri": transcript_uri},
        }
        self.started_jobs[TranscriptionJobName] = job
        print(f"[MockTranscribe] start_transcription_job -> {TranscriptionJobName}")

    def get_transcription_job(self, TranscriptionJobName):
        job = self.started_jobs.get(TranscriptionJobName)
        if not job:
            return {"TranscriptionJob": {"TranscriptionJobStatus": "FAILED", "FailureReason": "Job not found"}}
        return {"TranscriptionJob": job}


class MockGeminiClient:
    def __init__(self, api_key=None):
        self.api_key = api_key

    class models:
        @staticmethod
        def generate(model, input):
            class Result:
                def __init__(self, text):
                    self.output_text = text
            summary_text = (
                "• Summary (mock): Meeting planned Q1 roadmap.\n"
                "• Key point 1: Priorities set.\n"
                "• Key point 2: Owners assigned.\n"
                "• Key point 3: Deadlines discussed.\n"
                "• Key point 4: Follow-ups scheduled.\n\n"
                "Answer: The meeting objective was to plan the Q1 roadmap."
            )
            return Result(summary_text)


def mock_boto3_client_factory(bucket_name, transcript_key):
    def _client(service_name, *args, **kwargs):
        if service_name == "s3":
            return MockS3Client(bucket_name)
        if service_name == "transcribe":
            return MockTranscribeClient(transcript_key)
        raise ValueError(f"Mock boto3 client for service '{service_name}' is not implemented.")
    return _client


def mock_genai_client_factory():
    def _client(api_key=None):
        return MockGeminiClient(api_key=api_key)
    return _client


# --- Real AWS helpers (used when REAL_CLOUD=True) ---
def upload_file_to_s3(local_path: str, bucket: str, key: str, s3_client):
    """
    Upload a local file to S3 using the provided boto3 s3_client.
    Returns the S3 key and S3 URI.
    """
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"Local audio file not found: {local_path}")
    print(f"[Upload] Uploading {local_path} -> s3://{bucket}/{key}")
    # Use upload_file for streaming large files
    s3_client.upload_file(local_path, bucket, key)
    s3_uri = f"s3://{bucket}/{key}"
    print(f"[Upload] Completed: {s3_uri}")
    return key, s3_uri


def wait_for_summary_in_s3(bucket: str, original_key: str, s3_client, timeout: int = 300, interval: int = 5, output_prefix: str = OUTPUT_PREFIX):
    """
    Poll S3 for the summary file written by the Lambda.
    Summary key convention: {output_prefix}{base_name}.summary.json
    """
    base_name = original_key.split("/")[-1]
    summary_key = f"{output_prefix}{base_name}.summary.json"
    print(f"[Poll] Waiting for summary at s3://{bucket}/{summary_key} (timeout {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            obj = s3_client.get_object(Bucket=bucket, Key=summary_key)
            body = obj["Body"].read().decode("utf-8")
            print(f"[Poll] Summary found: s3://{bucket}/{summary_key}")
            return summary_key, body
        except Exception:
            time.sleep(interval)
    raise TimeoutError(f"Summary not found within {timeout} seconds: s3://{bucket}/{summary_key}")


# --- Local test runner functions (mock + real) ---
def run_presign_test(use_real=False, real_s3_client=None):
    if not INPUT_BUCKET_NAME:
        print("ERROR: Please set INPUT_BUCKET_NAME in your .env file before local events.")
        return

    presign_event = {
        "body": json.dumps({"fileName": "user_recording_123.wav"}),
        "httpMethod": "POST",
        "headers": {"Content-Type": "application/json"},
        "requestContext": {}
    }

    print("\n--- Local Runner: Simulating Presign API POST ---")
    if use_real and real_s3_client:
        # If real mode, let presign_handler use the real s3 client
        presign_module.s3_client = real_s3_client
    else:
        presign_module.s3_client = MockS3Client(INPUT_BUCKET_NAME)

    try:
        presign_result = presign_module.presign_handler(event=presign_event, context={})
    except Exception as e:
        print("Presign handler raised an exception during local run:")
        raise

    print("\n--- SIMULATION RESULT (Presign) ---")
    print(json.dumps(presign_result, ensure_ascii=False, indent=2))


def run_s3_flow_test(use_real=False, audio_path=None, invoke_lambda=False, lambda_name=None):
    if not INPUT_BUCKET_NAME:
        print("ERROR: Please set INPUT_BUCKET_NAME in your .env file before local events.")
        return

    # default test key if not uploading real file
    test_audio_key = "audio/user_recording_123.m4a"
    transcript_json_key = test_audio_key  # mock transcript path

    # If real mode and audio_path provided, upload the file to S3 and use that key
    if use_real:
        if not audio_path:
            print("ERROR: REAL_CLOUD mode requires AUDIO_PATH environment variable pointing to a local audio file.")
            return
        import boto3
        real_s3 = boto3.client("s3")
        # choose a key name (timestamped to avoid collisions)
        timestamp = int(time.time())
        base_name = os.path.basename(audio_path)
        test_audio_key = f"audio/{timestamp}_{base_name}"
        transcript_json_key = test_audio_key
        # upload file
        try:
            upload_file_to_s3(audio_path, INPUT_BUCKET_NAME, test_audio_key, real_s3)
        except Exception as e:
            print(f"Upload failed: {e}")
            return
    else:
        # mock mode: set mocks inside module
        voice_handler_module.s3_client = MockS3Client(INPUT_BUCKET_NAME)
        voice_handler_module.transcribe_client = MockTranscribeClient(transcript_json_key)
        voice_handler_module.genai = mock.MagicMock()
        voice_handler_module.genai.Client = mock_genai_client_factory()

    # Build a fake S3 event (used both for local invoke and for invoking Lambda directly)
    test_event = {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": os.environ.get("TRANSCRIBE_REGION", TRANSCRIBE_REGION),
                "eventTime": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "localTest",
                    "bucket": {"name": INPUT_BUCKET_NAME},
                    "object": {"key": test_audio_key, "size": os.path.getsize(audio_path) if (use_real and audio_path) else 123456}
                }
            }
        ]
    }

    print("\n--- Local Runner: S3 flow ---")
    print(f"Bucket: {INPUT_BUCKET_NAME}")
    print(f"Object Key: {test_audio_key}")
    print(f"Mode: {'REAL CLOUD' if use_real else 'MOCK'}")
    if use_real and invoke_lambda:
        print(f"Will invoke Lambda: {lambda_name}")

    # If real and invoke_lambda requested, call Lambda invoke (async)
    if use_real and invoke_lambda:
        import boto3
        lambda_client = boto3.client("lambda")
        try:
            payload = json.dumps(test_event).encode("utf-8")
            print(f"[Lambda Invoke] Invoking {lambda_name} asynchronously...")
            lambda_client.invoke(FunctionName=lambda_name, InvocationType="Event", Payload=payload)
            print("[Lambda Invoke] Invocation sent.")
        except Exception as e:
            print(f"[Lambda Invoke] Failed to invoke Lambda: {e}")
            return

        # After invoking, wait for summary to appear in S3
        s3_client = boto3.client("s3")
        try:
            summary_key, summary_body = wait_for_summary_in_s3(INPUT_BUCKET_NAME, test_audio_key, s3_client, timeout=SUMMARY_POLL_TIMEOUT, interval=SUMMARY_POLL_INTERVAL, output_prefix=OUTPUT_PREFIX)
            print("\n--- SUMMARY (from S3) ---")
            print(summary_body)
        except Exception as e:
            print(f"[Poll] Error while waiting for summary: {e}")
            return

    elif use_real and not invoke_lambda:
        # Real mode but not invoking Lambda directly: assume S3 trigger will run the deployed Lambda automatically.
        print("[Info] File uploaded to S3. Waiting for deployed S3-triggered Lambda to process and write summary...")
        import boto3
        s3_client = boto3.client("s3")
        try:
            summary_key, summary_body = wait_for_summary_in_s3(INPUT_BUCKET_NAME, test_audio_key, s3_client, timeout=SUMMARY_POLL_TIMEOUT, interval=SUMMARY_POLL_INTERVAL, output_prefix=OUTPUT_PREFIX)
            print("\n--- SUMMARY (from S3) ---")
            print(summary_body)
        except Exception as e:
            print(f"[Poll] Error while waiting for summary: {e}")
            return

    else:
        # Mock/local invocation: call the handler directly (no real AWS calls)
        try:
            result = voice_handler_module.agent_handler(event=test_event, context={})
        except Exception as e:
            print("Handler raised an exception during local run:")
            raise
        print("\n--- SIMULATION RESULT (S3 flow - mock) ---")
        print(json.dumps(result, ensure_ascii=False, indent=2))


# --- Main entrypoint ---
if __name__ == "__main__":
    # Run presign test (mock or real depending on REAL_CLOUD)
    if REAL_CLOUD:
        import boto3
        validate_real_cloud_config()
        real_s3_client = boto3.client("s3")
        run_presign_test(use_real=True, real_s3_client=real_s3_client)
    else:
        run_presign_test(use_real=False)

    # Run S3 flow test (mock or real)
    run_s3_flow_test(use_real=REAL_CLOUD, audio_path=AUDIO_PATH, invoke_lambda=INVOKE_LAMBDA, lambda_name=LAMBDA_NAME)
