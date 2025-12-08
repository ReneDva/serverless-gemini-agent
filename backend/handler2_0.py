# handler2_0.py
# Serverless Voice Agent with audio splitting, noise reduction, parallel transcription, and merge

import os, json, uuid, time, urllib.parse, logging, re
from typing import Tuple, Optional, List
import boto3
from botocore.exceptions import ClientError
from google import genai
import math
from pydub import AudioSegment, effects
import os
os.environ["PATH"] += ":/opt/bin"


log = logging.getLogger()
log.setLevel(logging.INFO)


# --- Environment variables ---
INPUT_BUCKET_NAME = os.environ.get("INPUT_BUCKET_NAME")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "summaries/")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
TRANSCRIBE_REGION = os.environ.get("TRANSCRIBE_REGION", "us-east-1")
TRANSCRIBE_LANGUAGE = os.environ.get("TRANSCRIBE_LANGUAGE", "he-IL")  # עברית

session = boto3.session.Session()
s3_client = session.client("s3", region_name="us-east-1")
transcribe_client = session.client("transcribe", region_name=TRANSCRIBE_REGION)





# --- Utilities ---
def _parse_s3_event(event) -> Tuple[str, str]:
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
    return bucket, key

def split_audio(local_path: str, chunk_length_ms: int = 120000) -> list:
    """פיצול קובץ אודיו לקטעים של עד 2 דקות"""
    audio = AudioSegment.from_file(local_path)
    if len(audio) <= chunk_length_ms:
        out_path = f"/tmp/chunk_0.wav"
        audio.export(out_path, format="wav")
        log.info("קובץ קצר – נשמר כיחידה אחת באורך %dms", len(audio))
        return [out_path]

    chunks = []
    for i in range(0, len(audio), chunk_length_ms):
        chunk = audio[i:i+chunk_length_ms]
        out_path = f"/tmp/chunk_{i//chunk_length_ms}.wav"
        chunk.export(out_path, format="wav")
        chunks.append(out_path)
        log.info("נוצר chunk %d באורך %dms", i//chunk_length_ms, len(chunk))
    return chunks

def _infer_media_format(key: str) -> str:
    ext = key.split(".")[-1].lower()
    return {"wav":"wav","mp3":"mp3","flac":"flac","ogg":"ogg","mp4":"mp4","m4a":"mp4"}.get(ext, ext)

def _start_transcribe_job(bucket: str, key: str) -> str:
    # Build job name and media URI
    job_name = f"gemini-transcribe-{uuid.uuid4()}"
    media_uri = f"s3://{bucket}/{key}"
    media_format = _infer_media_format(key)

    # Preserve the full chunk path in the output key so transcripts are grouped per original file
    prefix = key.rsplit("/", 1)[0]   # e.g. "chunks/<base_name>"
    file_name = key.split("/")[-1]   # e.g. "part_000.wav"
    out_key = f"transcriptions/{prefix}/{file_name}.json"

    log.info("Starting Transcribe job: job_name=%s, media_uri=%s, format=%s, output_key=%s",
             job_name, media_uri, media_format, out_key)

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": media_uri},
        MediaFormat=media_format,
        LanguageCode=TRANSCRIBE_LANGUAGE,
        OutputBucketName=INPUT_BUCKET_NAME,
        OutputKey=out_key
    )
    log.info("Transcribe job %s submitted successfully", job_name)
    return job_name

# --- NEW: merge transcripts ---
def _merge_transcripts(bucket: str, prefix: str) -> str:
    """Merge all transcript parts under transcriptions/prefix_* into one string"""
    log.info("Starting merge of transcripts under prefix: transcriptions/%s", prefix)
    resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=f"transcriptions/{prefix}")
    texts = []
    for idx, obj in enumerate(sorted(resp.get("Contents", []), key=lambda x: x["Key"])):
        log.info("Reading transcript file #%d from S3: %s", idx, obj["Key"])
        body = s3_client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read().decode("utf-8")
        payload = json.loads(body)
        t = payload.get("results", {}).get("transcripts", [])
        if t:
            text = t[0].get("transcript", "")
            log.info("Transcript #%d loaded from %s – length %d characters", idx, obj["Key"], len(text))
            texts.append(text)
    merged = "\n".join(texts)
    log.info("Merge complete – merged %d transcripts, total length %d characters", len(texts), len(merged))
    return merged


def _wait_for_transcribe(job_name: str, timeout_sec: int = 600, poll_sec: int = 5) -> Optional[dict]:
    start = time.time()
    while time.time() - start < timeout_sec:
        resp = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
        job = resp["TranscriptionJob"]
        status = job["TranscriptionJobStatus"]
        if status == "COMPLETED": return job
        if status == "FAILED": raise RuntimeError(f"Transcribe job failed: {job.get('FailureReason')}")
        time.sleep(poll_sec)
    return None

def _read_transcript_from_s3(transcript_uri: str) -> str:
    parsed = urllib.parse.urlparse(transcript_uri)
    path = parsed.path.lstrip("/")
    bucket, key = path.split("/",1)
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    data = obj["Body"].read().decode("utf-8")
    payload = json.loads(data)
    transcripts = payload.get("results", {}).get("transcripts", [])
    return transcripts[0].get("transcript","") if transcripts else ""

# --- Gemini summarizer (כמו בקוד שלך) ---
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

# --- Noise reduction helper ---
def preprocess_audio(local_path: str, out_path: str):
    """
    סינון רעשים בסיסי: נורמליזציה של עוצמת הקול והסרת שקטים קיצוניים.
    """
    audio = AudioSegment.from_file(local_path)
    # נורמליזציה של עוצמת הקול
    normalized = effects.normalize(audio)
    # אפשרות: הסרת שקטים ארוכים מההתחלה והסוף
    cleaned = normalized.strip_silence(silence_len=1000, silence_thresh=-40)
    cleaned.export(out_path, format="wav")
    return out_path

def agent_handler(event, context):
    log.info("agent_handler invoked with event: %s", json.dumps(event))

    # Parse S3 event
    bucket, key = _parse_s3_event(event)
    base_name = key.split("/")[-1].rsplit(".", 1)[0]
    log.info("Parsed S3 event: bucket=%s, key=%s, base_name=%s", bucket, key, base_name)

    # Download file to /tmp
    local_path = f"/tmp/{base_name}.wav"
    log.info("Downloading original file from S3 to %s", local_path)
    s3_client.download_file(bucket, key, local_path)
    log.info("Original file downloaded successfully")

    # Noise reduction
    clean_path = f"/tmp/{base_name}_clean.wav"
    log.info("Starting noise reduction: input=%s, output=%s", local_path, clean_path)
    preprocess_audio(local_path, clean_path)
    log.info("Noise reduction complete, cleaned file saved at %s", clean_path)

    # Split audio
    log.info("Splitting audio file into chunks (max 2 minutes each)")
    chunk_paths = split_audio(clean_path)
    if len(chunk_paths) == 1:
        log.info("Audio is short – kept as a single chunk: %s", chunk_paths[0])
    else:
        log.info("Audio split into %d chunks: %s", len(chunk_paths), chunk_paths)

    transcripts = []
    for idx, chunk_path in enumerate(chunk_paths):
        part_key = f"chunks/{base_name}/part_{idx:03d}.wav"
        log.info("[Chunk %d] Uploading to S3 with key %s", idx, part_key)
        s3_client.upload_file(chunk_path, bucket, part_key)
        log.info("[Chunk %d] Upload completed", idx)

        # Transcribe each chunk
        log.info("[Chunk %d] Starting Transcribe job for %s", idx, part_key)
        job_name = _start_transcribe_job(bucket, part_key)
        log.info("[Chunk %d] Transcribe job started: %s", idx, job_name)

        job = _wait_for_transcribe(job_name)
        if not job or "TranscriptionJob" not in job:
            log.error("Unexpected Transcribe response for job %s: %s", job_name, job)
            raise RuntimeError("No TranscriptionJob in response")
        status = job["TranscriptionJob"]["TranscriptionJobStatus"]
        log.info("Transcribe job %s finished with status: %s", job_name, status)

        transcript_uri = job["Transcript"]["TranscriptFileUri"]
        log.info("[Chunk %d] Fetching transcript from URI: %s", idx, transcript_uri)
        text = _read_transcript_from_s3(transcript_uri)
        log.info("[Chunk %d] Transcript retrieved – length %d characters", idx, len(text))
        transcripts.append(text)

    # Merge transcripts
    log.info("Merging %d transcripts into one full text", len(transcripts))
    full_text = "\n".join(transcripts)
    log.info("Merged transcript complete – total length %d characters", len(full_text))

    # Summarize with Gemini
    log.info("Sending merged transcript to Gemini summarizer")
    summary = _gemini_summarize_and_answer(full_text)
    log.info("Gemini summarizer returned summary with %d sections", len(summary.get("sections", [])))

    # Write summary to S3
    out_key = f"{OUTPUT_PREFIX}{base_name}.summary.json"
    log.info("Writing summary JSON to S3: bucket=%s, key=%s", bucket, out_key)
    s3_client.put_object(
        Bucket=bucket,
        Key=out_key,
        Body=json.dumps(summary, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json"
    )
    log.info("Summary written successfully to S3")

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok", "summary_key": out_key}, ensure_ascii=False)
    }

def summary_handler(event, context):
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
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return {
                "statusCode": 404,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "OPTIONS,GET"
                },
                "body": json.dumps({"error": "Summary not ready yet"})
            }
        else:
            return {
                "statusCode": 500,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Allow-Methods": "OPTIONS,GET"
                },
                "body": json.dumps({"error": str(e)})
            }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "OPTIONS,GET"
            },
            "body": json.dumps({"error": str(e)})
        }

