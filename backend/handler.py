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
import os
import sys
import logging

# Google GenAI (Gemini) SDK
# pip install google-genai (or google-generativeai depending on your chosen SDK)
from google import genai
import json, re
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
import asyncio

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Environment variables (read once) ---
INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "summaries/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
TRANSCRIBE_REGION = os.environ.get("TRANSCRIBE_REGION", "us-east-1")
TRANSCRIBE_LANGUAGE = os.environ.get("TRANSCRIBE_LANGUAGE", "en-US")

# Validate required values
def validate_env():
    missing = []
    if not os.environ.get("INPUT_BUCKET_NAME"):
        missing.append("INPUT_BUCKET_NAME")
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

validate_env()

# --- AWS clients (create after env validated) ---
session = boto3.session.Session()
s3_client = session.client("s3", region_name="us-east-1")
transcribe_client = session.client("transcribe", region_name=TRANSCRIBE_REGION)

log.info("Environment loaded: INPUT_BUCKET=%s, MODEL=%s, TRANSCRIBE_REGION=%s",
         INPUT_BUCKET_NAME, GEMINI_MODEL, TRANSCRIBE_REGION)
# Do NOT log GEMINI_API_KEY


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

def _transcription_exists(bucket: str, key: str) -> bool:
    """
    בדיקה אם כבר קיים תמלול עבור קובץ שמע מסוים.
    מחפש לפי שם הקובץ המקורי תחת transcriptions/<base_name>.json
    """
    base_name = key.split("/")[-1]
    transcript_key = f"transcriptions/{base_name}.json"
    try:
        s3_client.head_object(Bucket=bucket, Key=transcript_key)
        return True
    except s3_client.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            return False
        raise



async def _start_streaming_transcribe(bucket: str, key: str) -> str:
    # הורדת הקובץ מ-S3
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    audio_bytes = obj["Body"].read()

    client = TranscribeStreamingClient(region="us-east-1")
    stream = await client.start_stream_transcription(
        language_code="he-IL",
        media_sample_rate_hz=16000,
        media_encoding="pcm"
    )

    async def write_chunks():
        # כאן צריך לחתוך את audio_bytes ל-chunks ולשלוח
        await stream.input_stream.send_audio_event(audio_chunk=audio_bytes)
        await stream.input_stream.end_stream()

    async def read_results():
        transcript = []
        async for event in stream.output_stream:
            if event.transcript_event:
                for result in event.transcript_event.transcript.results:
                    if not result.is_partial:
                        transcript.append(result.alternatives[0].transcript)
        return " ".join(transcript)

    await asyncio.gather(write_chunks(), read_results())
    final_text = await read_results()

    # כתיבה ל-S3 כמו בקוד הקיים
    base_name = key.split("/")[-1]
    out_key = f"transcriptions/{base_name}.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=out_key,
        Body=json.dumps({"results": {"transcripts": [{"transcript": final_text}]}}).encode("utf-8"),
        ContentType="application/json"
    )
    return final_text

def _start_transcribe_job(bucket: str, key: str) -> str:
    """
    מפעיל Job חדש ב־Transcribe עבור קובץ שמע.
    שומר את התמלול תמיד תחת transcriptions/<base_name>.json
    """
    job_name = f"gemini-transcribe-{uuid.uuid4()}"  # שם ייחודי ל־Job
    media_uri = f"s3://{bucket}/{key}"
    media_format = _infer_media_format(key)

    base_name = key.split("/")[-1]
    out_key = f"transcriptions/{base_name}.json"

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": media_uri},
        MediaFormat=media_format,
        LanguageCode=TRANSCRIBE_LANGUAGE,
        OutputBucketName=INPUT_BUCKET_NAME,
        OutputKey=out_key
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


def _gemini_summarize_and_answer(text: str, question: str = "") -> dict:
    """
    Request a structured summary from Gemini and return sections with titles and bullets.
    Returns: { "sections": [ {"title": str, "bullets": [str, ...]}, ... ], "raw": str }
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Prompt: ask for structured JSON output with sections and bullets in Hebrew.
    prompt = (
        "אתה מקבל תמליל של אינטראקציה אנושית: פגישה, שיעור, הרצאה או שיחת טלפון.\n"
        "אנא הפק תקציר מובנה בפורמט JSON בלבד.\n"
        "ה‑JSON חייב להיות אובייקט עם המפתחות הבאים:\n"
        "- sections: רשימה של אובייקטים, כל אחד עם 'title' בעברית ו‑'bullets' (מערך נקודות בעברית).\n"
        "- participants: רשימת שמות או תפקידים אם מופיעים בתמליל. אם לא מופיעים שמות, השתמש ב'דובר א', 'דובר ב'.\n"
        "- decisions: החלטות או הסכמות שהתקבלו.\n"
        "- action_items: משימות להמשך או פעולות שסוכמו.\n"
        "- questions: שאלות שעלו.\n\n"
        "הוראות מותאמות לפי סוג התמליל:\n"
        "- אם מדובר בשיחת טלפון: התמקד בזיהוי הדוברים, בהסכמות קצרות, בשאלות ישירות ובמשימות פשוטות.\n"
        "- אם מדובר בפגישה: התמקד בזיהוי משתתפים, נושאים מרכזיים, החלטות רשמיות ומשימות להמשך.\n"
        "- אם מדובר בהרצאה או שיעור: התמקד בנושאים שהוסברו, דוגמאות שהובאו, שאלות תלמידים/קהל, והמלצות להמשך לימוד.\n"
        "- אם לא ניתן לזהות את סוג התמליל: הפק סיכום כללי לפי המבנה הנדרש.\n\n"
        "אל תוסיף טקסט נוסף מחוץ ל‑JSON.\n"
        "דוגמה:\n"
        '{\n'
        '  "sections": [\n'
        '    { "title": "נושא א", "bullets": ["נקודה1","נקודה2"] },\n'
        '    { "title": "נושא ב", "bullets": ["נקודה1"] }\n'
        '  ],\n'
        '  "participants": ["דובר א","דובר ב"],\n'
        '  "decisions": ["הוסכם להיפגש ביום ראשון"],\n'
        '  "action_items": ["דובר א ישלח מסמך","דובר ב יבדוק זמינות"],\n'
        '  "questions": ["מתי הפגישה הבאה?"]\n'
        '}\n\n'
        "תמליל:\n"
        f"{text}\n"
    )

    # Call the SDK using the correct parameter name 'contents'.
    result = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={"temperature": 0.0}
    )

    # Extract raw text from the SDK response using common response shapes.
    def _extract_raw_text(res):
        if hasattr(res, "output_text"):
            try:
                t = getattr(res, "output_text")
                if t:
                    return t
            except Exception:
                pass
        out = getattr(res, "output", None)
        if out:
            try:
                first = out[0]
                if hasattr(first, "content"):
                    c = first.content
                    if isinstance(c, (list, tuple)) and len(c) > 0:
                        texts = []
                        for part in c:
                            if hasattr(part, "text"):
                                texts.append(getattr(part, "text") or "")
                            elif isinstance(part, dict) and "text" in part:
                                texts.append(part["text"] or "")
                        joined = "\n".join([t for t in texts if t])
                        if joined:
                            return joined
                if hasattr(first, "text"):
                    return getattr(first, "text") or ""
                if isinstance(first, dict) and "text" in first:
                    return first["text"] or ""
            except Exception:
                pass
        try:
            return str(res)
        except Exception:
            return ""

    raw_text = _extract_raw_text(result)

    # Try to parse JSON directly from the model output.

    def _parse_json_from_text(s: str):
        if not s:
            return None
        # Attempt to find a JSON object in the text
        # Find first '{' and last '}' to extract candidate JSON substring
        start = s.find("{")
        end = s.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = s[start:end+1]
        try:
            parsed = json.loads(candidate)
            # Validate structure
            if isinstance(parsed, dict) and "sections" in parsed and isinstance(parsed["sections"], list):
                # Normalize entries
                sections = []
                for sec in parsed["sections"]:
                    title = sec.get("title", "").strip() if isinstance(sec, dict) else ""
                    bullets = []
                    if isinstance(sec, dict):
                        b = sec.get("bullets", [])
                        if isinstance(b, list):
                            bullets = [str(x).strip() for x in b if x and str(x).strip()]
                    sections.append({"title": title or "Untitled", "bullets": bullets})
                return {"sections": sections}
        except Exception:
            return None
        return None

    parsed = _parse_json_from_text(raw_text)

    # If JSON parse succeeded, return it.
    if parsed:
        return {"sections": parsed["sections"], "raw": raw_text}

    # Fallback: heuristically parse headings and bullets from plain text.
    def _heuristic_parse(s: str):
        lines = [ln.rstrip() for ln in s.splitlines()]
        sections = []
        current_title = None
        current_bullets = []

        # Patterns that indicate a heading line
        heading_patterns = [
            re.compile(r'^\s*#{1,6}\s*(.+)$'),  # Markdown headings
            re.compile(r'^\s*([A-Zא-ת][\w\s\-]{2,60}):\s*$'),  # "Title:" line (Latin or Hebrew)
            re.compile(r'^\s*([A-Zא-ת][\w\s\-]{2,60})\s*$')  # Standalone Title line (Latin or Hebrew)
        ]

        # Bullet patterns
        bullet_re = re.compile(r'^\s*([-•*]\s+)(.+)$')
        numbered_re = re.compile(r'^\s*\d+[\.\)]\s+(.+)$')

        for ln in lines:
            if not ln.strip():
                continue
            # Check for explicit bullet
            m = bullet_re.match(ln)
            if m:
                text = m.group(2).strip()
                if current_title is None:
                    current_title = "General"
                current_bullets.append(text)
                continue
            m2 = numbered_re.match(ln)
            if m2:
                text = m2.group(1).strip()
                if current_title is None:
                    current_title = "General"
                current_bullets.append(text)
                continue
            # Check for heading patterns
            is_heading = False
            for hp in heading_patterns:
                mh = hp.match(ln)
                if mh:
                    # flush previous section
                    if current_title or current_bullets:
                        sections.append({
                            "title": current_title or "General",
                            "bullets": current_bullets
                        })
                    current_title = mh.group(1).strip()
                    current_bullets = []
                    is_heading = True
                    break
            if is_heading:
                continue
            # If line is long and we have a current section, treat as bullet
            if current_title:
                current_bullets.append(ln.strip())
            else:
                # Start a general section
                current_title = "General"
                current_bullets.append(ln.strip())

        # flush last
        if current_title or current_bullets:
            sections.append({
                "title": current_title or "General",
                "bullets": current_bullets
            })
        # Normalize: ensure bullets are strings and trimmed
        for sec in sections:
            sec["title"] = sec["title"].strip() if sec.get("title") else "Untitled"
            sec["bullets"] = [b.strip() for b in sec.get("bullets", []) if b and b.strip()]
        return sections

    sections = _heuristic_parse(raw_text)

    return {"sections": sections, "raw": raw_text}


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
    - Checks if transcript already exists under transcriptions/
    - If not, starts Transcribe and waits for completion
    - Reads transcript
    - Summarizes with Gemini
    - Writes summary JSON to S3 under summaries/
    """

    log.info("Loaded ENV: INPUT_BUCKET=%s, MODEL=%s, REGION=%s",
             INPUT_BUCKET_NAME, GEMINI_MODEL, TRANSCRIBE_REGION)

    # Basic validation
    if not GEMINI_API_KEY:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps("ERROR: GEMINI_API_KEY missing")
        }
    if not INPUT_BUCKET_NAME:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps("ERROR: INPUT_BUCKET_NAME missing")
        }

    # Parse S3 event
    try:
        bucket, key = _parse_s3_event(event)
        log.info("Received S3 event: bucket=%s, key=%s", bucket, key)
    except (KeyError, IndexError, ValueError) as e:
        return {
            "statusCode": 202,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps(f"Invalid S3 event: {str(e)}")
        }

    # Ensure audio files are under recordings/
    if not key.startswith("recordings/"):
        log.warning("Unexpected key outside recordings/: %s", key)

    # Check if transcript already exists
    base_name = key.split("/")[-1]
    transcript_key = f"transcriptions/{base_name}.json"

    try:
        if _transcription_exists(bucket, key):
            log.info("Transcript already exists for %s, skipping Transcribe", key)
            obj = s3_client.get_object(Bucket=bucket, Key=transcript_key)
            transcript_text = obj["Body"].read().decode("utf-8")
        else:
            job_name = _start_transcribe_job(bucket, key)
            log.info("Transcribe job started: %s for s3://%s/%s", job_name, bucket, key)

            job = _wait_for_transcribe(job_name)
            if job is None:
                return {
                    "statusCode": 504,
                    "headers": {"Access-Control-Allow-Origin": "*"},
                    "body": json.dumps("Transcribe timed out")
                }

            transcript_uri = job["Transcript"]["TranscriptFileUri"]
            transcript_text = _read_transcript_from_s3(transcript_uri)

        if not transcript_text.strip():
            return {
                "statusCode": 200,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps("No transcript text found")
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps(f"Transcribe error: {str(e)}")
        }

    # Metadata question (optional)
    question = "What was the meeting objective according to the transcript?"
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
        meta = head.get("Metadata", {})
        if "question" in meta:
            question = meta["question"]
    except Exception:
        pass

    # Call Gemini
    try:
        summary = _gemini_summarize_and_answer(transcript_text, question)
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps(f"Gemini error: {str(e)}")
        }

    # Write summary to S3
    try:
        out_key = _write_summary_to_s3(key, summary)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,GET"
            },
            "body": json.dumps({"status": "ok", "summary_key": out_key}, ensure_ascii=False)
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps(f"S3 write error: {str(e)}")
        }

def summary_handler(event, context):
    """
    Lambda entrypoint for HTTP GET requests to fetch a summary.
    This function:
    - Reads the 'fileName' query parameter from the request
    - Constructs the expected summary object key in S3 (OUTPUT_PREFIX + fileName + ".summary.json")
    - Retrieves the summary JSON from S3
    - Returns the JSON with proper CORS headers so that browsers can access it

    Expected request:
      GET /summary?fileName=<original-audio-file-name>

    Example:
      If the original file was "user_recording_123.m4a",
      the summary will be stored as "summaries/user_recording_123.m4a.summary.json"
    """

    # Extract fileName from query parameters
    params = event.get("queryStringParameters") or {}
    file_name = params.get("fileName")
    if not file_name:
        return {
            "statusCode": 400,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,GET"
            },
            "body": json.dumps({"error": "Missing fileName query parameter"})
        }

    # Build the summary key
    out_key = f"{OUTPUT_PREFIX}{file_name}.summary.json"

    try:
        obj = s3_client.get_object(Bucket=INPUT_BUCKET_NAME, Key=out_key)
        body = obj["Body"].read().decode("utf-8")
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,GET"
            },
            "body": body
        }
    except s3_client.exceptions.NoSuchKey:
        # Summary file not ready yet
        return {
            "statusCode": 404,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,GET"
            },
            "body": json.dumps({"error": "Summary not ready yet"})
        }
    except Exception as e:
        # Other unexpected errors
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,GET"
            },
            "body": json.dumps({"error": str(e)})
        }
