# tests/local_runner.py
"""
Local runner for the Serverless Gemini Agent.
Place this file in tests/ and run with: python tests/local_runner.py

This script:
- Loads .env for INPUT_BUCKET_NAME and GEMINI_API_KEY
- Mocks boto3 clients (s3, transcribe) and google.genai.Client
- Simulates an S3 ObjectCreated event and invokes backend/handler.agent_handler
"""

import os
import json
import urllib.parse
from unittest import mock

from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

# Ensure project root is importable (adjust if needed)
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Import the handler to test
try:
    from backend import handler as voice_handler_module
except Exception as e:
    print("ERROR: Could not import backend.handler. Make sure your project structure is correct.")
    raise

# Read env vars used by the handler
INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "DUMMY_KEY_FOR_LOCAL_TESTS")


# --- Sample transcript JSON that AWS Transcribe would normally write to S3 ---
SAMPLE_TRANSCRIBE_JSON = {
    "results": {
        "transcripts": [
            {"transcript": "This is a sample transcript text produced for local testing. The meeting objective was to plan the Q1 roadmap."}
        ]
    }
}

# --- Mock implementations for boto3 clients ---
class MockS3Client:
    def __init__(self, bucket_name):
        self.bucket = bucket_name
        self.storage = {}  # in-memory store for put_object calls

    def get_object(self, Bucket, Key):
        # Return the SAMPLE_TRANSCRIBE_JSON when asked for the transcript JSON key
        # Simulate reading the JSON that Transcribe would have written
        # If Key ends with .json, return the sample transcript
        if Key.endswith(".json"):
            body = json.dumps(SAMPLE_TRANSCRIBE_JSON).encode("utf-8")
            return {"Body": MockBody(body)}
        # If reading original audio object metadata (head_object), return empty metadata
        if Key.endswith(".m4a") or Key.endswith(".mp3") or Key.endswith(".wav"):
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}
        # If reading a stored summary (put earlier), return it from in-memory storage
        if Key in self.storage:
            return {"Body": MockBody(self.storage[Key].encode("utf-8"))}
        raise FileNotFoundError(f"MockS3Client: Key not found: {Key}")

    def put_object(self, Bucket, Key, Body, ContentType="application/json"):
        # store the body in memory for inspection
        self.storage[Key] = Body.decode("utf-8") if isinstance(Body, (bytes, bytearray)) else str(Body)
        print(f"[MockS3] put_object -> Bucket: {Bucket}, Key: {Key}, ContentType: {ContentType}")
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def head_object(self, Bucket, Key):
        # Return empty metadata by default
        return {"Metadata": {}}

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn=3600):
        # Simple fake URL for presign tests
        bucket = Params.get("Bucket")
        key = Params.get("Key")
        return f"https://mock-s3/{bucket}/{urllib.parse.quote(key)}?expires_in={ExpiresIn}"


class MockBody:
    def __init__(self, data_bytes):
        self._data = data_bytes

    def read(self):
        return self._data


class MockTranscribeClient:
    def __init__(self, transcript_key):
        self.transcript_key = transcript_key
        self.started_jobs = {}

    def start_transcription_job(self, TranscriptionJobName, Media, MediaFormat, LanguageCode, OutputBucketName):
        # Simulate starting a job; record it and pretend it's completed immediately
        transcript_uri = f"https://s3.amazonaws.com/{OutputBucketName}/{self.transcript_key}.json"
        job = {
            "TranscriptionJobName": TranscriptionJobName,
            "Media": Media,
            "MediaFormat": MediaFormat,
            "LanguageCode": LanguageCode,
            "OutputBucketName": OutputBucketName,
            "TranscriptionJobStatus": "COMPLETED",
            "Transcript": {
                "TranscriptFileUri": transcript_uri
            }
        }
        self.started_jobs[TranscriptionJobName] = job
        print(f"[MockTranscribe] start_transcription_job -> {TranscriptionJobName}")

    def get_transcription_job(self, TranscriptionJobName):
        job = self.started_jobs.get(TranscriptionJobName)
        if not job:
            return {"TranscriptionJob": {"TranscriptionJobStatus": "FAILED", "FailureReason": "Job not found"}}
        return {"TranscriptionJob": job}


# --- Mock for Google GenAI (Gemini) client ---
class MockGeminiClient:
    def __init__(self, api_key=None):
        self.api_key = api_key

    class models:
        @staticmethod
        def generate(model, input):
            # Return a simple object with output_text attribute similar to real SDK
            class Result:
                def __init__(self, text):
                    self.output_text = text
            # Create a deterministic mock summary based on the input
            summary_text = (
                "• Summary (mock): Meeting planned Q1 roadmap.\n"
                "• Key point 1: Priorities set.\n"
                "• Key point 2: Owners assigned.\n"
                "• Key point 3: Deadlines discussed.\n"
                "• Key point 4: Follow-ups scheduled.\n\n"
                "Answer: The meeting objective was to plan the Q1 roadmap."
            )
            return Result(summary_text)


# --- Helper to patch boto3.client and google.genai.Client ---
def mock_boto3_client_factory(bucket_name, transcript_key):
    def _client(service_name, *args, **kwargs):
        if service_name == "s3":
            return MockS3Client(bucket_name)
        if service_name == "transcribe":
            return MockTranscribeClient(transcript_key)
        # default fallback
        raise ValueError(f"Mock boto3 client for service '{service_name}' is not implemented.")
    return _client


def mock_genai_client_factory():
    def _client(api_key=None):
        return MockGeminiClient(api_key=api_key)
    return _client


# --- Main local runner ---
if __name__ == "__main__":
    # Basic checks
    if not INPUT_BUCKET_NAME:
        print("ERROR: Please set INPUT_BUCKET_NAME in your .env file before local events.")
        raise SystemExit(1)

    # The key (audio file) we simulate uploading
    test_audio_key = "audio/user_recording_123.m4a"
    transcript_json_key = "audio/user_recording_123.m4a"  # Transcribe will write {key}.json in our mock
    # after importing voice_handler_module
    voice_handler_module.s3_client = MockS3Client(INPUT_BUCKET_NAME)
    voice_handler_module.transcribe_client = MockTranscribeClient(transcript_json_key)
    # replace genai client factory used inside handler
    voice_handler_module.genai = mock.MagicMock()
    voice_handler_module.genai.Client = mock_genai_client_factory()


    # Build a fake S3 event
    test_event = {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": os.environ.get("TRANSCRIBE_REGION", "us-east-1"),
                "eventTime": "2025-11-24T17:00:00.000Z",
                "eventName": "ObjectCreated:Put",
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "testConfigRule",
                    "bucket": {"name": INPUT_BUCKET_NAME},
                    "object": {"key": test_audio_key, "size": 123456}
                }
            }
        ]
    }

    print("\n--- Local Runner: Simulating S3 ObjectCreated event ---")
    print(f"Bucket: {INPUT_BUCKET_NAME}")
    print(f"Object Key: {test_audio_key}\n")

    # Patch boto3.client and google.genai.Client inside the voice_handler_module
    with mock.patch("boto3.client", new=mock_boto3_client_factory(INPUT_BUCKET_NAME, transcript_json_key)):
        with mock.patch("google.genai.Client", new=mock_genai_client_factory()):
            # Now call the handler
            try:
                result = voice_handler_module.agent_handler(event=test_event, context={})
            except Exception as e:
                print("Handler raised an exception during local run:")
                raise

    print("\n--- SIMULATION RESULT ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("---------------------------\n")
