# handler2_0.py
# Serverless Voice Agent with audio splitting, noise reduction, parallel transcription, and merge

import os, json, uuid, time, urllib.parse, logging, re
from typing import Tuple, Optional, List
import boto3
from botocore.exceptions import ClientError
from google import genai
import math
from pydub import AudioSegment, effects


import concurrent.futures
os.environ["PATH"] += ":/opt/bin"


log = logging.getLogger()
log.setLevel(logging.DEBUG)


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

def split_audio(local_path: str, chunk_length_ms: int = 60000) -> list:
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


def sanitize_key(name: str) -> str:
    # החלפת כל תו שאינו מותר ב־Transcribe ל־"_"
    return re.sub(r"[^a-zA-Z0-9\-_.!*'()/&$@=;:+,?]", "_", name)


def _start_transcribe_job(bucket: str, base_name: str, part_key: str, idx: int) -> str:
    """
    Start a Transcribe job for a given chunk and save output under transcriptions/<base_name>/part_xxx.json
    """
    job_name = f"gemini-transcribe-{uuid.uuid4()}"
    media_uri = f"s3://{bucket}/{part_key}"
    media_format = _infer_media_format(part_key)

    out_key = f"transcriptions/{base_name}/part_{idx:03d}.json"

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


def _merge_transcripts(bucket: str, base_name: str) -> str:
    """Merge all transcript parts under transcriptions/<base_name>/ into one string"""
    prefix = f"transcriptions/{base_name}/"
    log.info("Starting merge of transcripts under prefix: %s", prefix)
    resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
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
        log.info("Polling job %s: status=%s", job_name, status)
        if status == "COMPLETED":
            return job
        if status == "FAILED":
            raise RuntimeError(f"Transcribe job failed: {job.get('FailureReason')}")
        time.sleep(poll_sec)
    return None

def _read_transcript_from_s3(bucket: str, base_name: str, idx: int) -> str:
    """
    Read transcript text from known S3 key: transcriptions/<base_name>/part_xxx.json
    """
    key = f"transcriptions/{base_name}/part_{idx:03d}.json"
    log.info("Reading transcript from s3://%s/%s", bucket, key)
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    data = obj["Body"].read().decode("utf-8")
    payload = json.loads(data)
    transcripts = payload.get("results", {}).get("transcripts", [])
    return transcripts[0].get("transcript", "") if transcripts else ""

def preprocess_audio(local_path: str, out_path: str):
    try:
        log.info("Preprocess: loading audio from %s", local_path)
        audio = AudioSegment.from_file(local_path)
        log.info("Preprocess: normalizing volume")
        normalized = effects.normalize(audio)
        log.info("Preprocess: stripping silence (len>=1000ms, thresh=-40dBFS)")
        cleaned = normalized.strip_silence(silence_len=1000, silence_thresh=-40)
        cleaned.export(out_path, format="wav")
        log.info("Preprocess: exported cleaned audio to %s", out_path)
        return out_path
    except Exception as e:
        log.error("Preprocess failed for %s: %s", local_path, e)
        raise

def _put_json(bucket: str, key: str, payload: dict):
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )

def _transcribe_part(bucket: str, base_name: str, part_key: str, idx: int) -> dict:
    # Start job
    job_name = _start_transcribe_job(bucket, base_name, part_key, idx)
    log.info("[Transcribe] Job started for %s: %s", part_key, job_name)

    # Wait complete
    job = _wait_for_transcribe(job_name)
    if not job:
        raise RuntimeError(f"Transcribe job timeout for {part_key}")
    status = job["TranscriptionJobStatus"]
    if status != "COMPLETED":
        raise RuntimeError(f"Transcribe job failed for {part_key}: {job.get('FailureReason')}")

    log.info("[Transcribe] Job %s completed for %s", job_name, part_key)

    # Fetch transcript text from known S3 key
    text = None
    for attempt in range(5):
        try:
            text = _read_transcript_from_s3(bucket, base_name, idx)
            log.info("[Transcribe] Transcript length for %s: %d chars", part_key, len(text))
            break
        except ClientError:
            time.sleep(2)

    if text is None:
        raise RuntimeError(f"Transcribe job failed for {part_key}")

    return {"part_key": part_key, "text": text}

def generate_internal_id() -> str:
    """יוצר מזהה פנימי ייחודי לכל קובץ"""
    return str(uuid.uuid4())

def _update_status(bucket: str, internal_id: str, original_name: str, **kwargs):
    """
    עדכון סטטוס: נשמר גם המזהה הפנימי וגם השם המקורי
    """
    status_key = f"statuses/{internal_id}.json"
    current = {}
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=status_key)
        current = json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        pass
    current.update({
        "updated_at": int(time.time()),
        "internal_id": internal_id,
        "original_name": original_name
    })
    current.update(kwargs)
    _put_json(bucket, status_key, current)
    log.info("Status updated: s3://%s/%s -> %s", bucket, status_key, current)

def _build_manifest(internal_id: str, original_name: str, part_keys: list[str]) -> dict:
    """
    בניית manifest: כולל גם את השם המקורי וגם את המזהה החדש
    """
    return {
        "internal_id": internal_id,
        "original_name": original_name,
        "created_at": int(time.time()),
        "total_parts": len(part_keys),
        "parts": [{"index": i, "s3_key": k} for i, k in enumerate(part_keys)],
        "transcriptions_prefix": f"transcriptions/{internal_id}/",
        "chunks_prefix": f"chunks/{internal_id}/",
        "summary_key": f"{OUTPUT_PREFIX}{original_name}.summary.json",
    }


def agent_handler(event, context):
    log.info("=== agent_handler invoked === event=%s", json.dumps(event))

    # Parse S3 event
    bucket, key = _parse_s3_event(event)
    original_name = key.split("/")[-1].rsplit(".", 1)[0]
    internal_id = generate_internal_id()
    log.info("[Init] bucket=%s, key=%s, original_name=%s, internal_id=%s", bucket, key, original_name, internal_id)

    _update_status(bucket, internal_id, original_name, stage="uploaded", source_key=key)

    # Download original file
    local_path = f"/tmp/{original_name}.wav"
    log.info("[Download] from s3://%s/%s -> %s", bucket, key, local_path)
    s3_client.download_file(bucket, key, local_path)
    log.info("[Download] completed")

    # Split (על השם המקורי)
    log.info("[Split] splitting audio into chunks (max 1 minute)")
    chunk_paths = split_audio(local_path, chunk_length_ms=60000)
    log.info("[Split] produced %d chunks", len(chunk_paths))

    # Preprocess each chunk separately and upload (שימוש במזהה החדש)
    part_keys = []
    for idx, chunk_path in enumerate(chunk_paths):
        clean_chunk_path = f"/tmp/{internal_id}_chunk_{idx:03d}_clean.wav"
        preprocess_audio(chunk_path, clean_chunk_path)
        part_key = f"chunks/{internal_id}/part_{idx:03d}.wav"
        s3_client.upload_file(clean_chunk_path, bucket, part_key)
        log.info("[Chunk %d] uploaded to s3://%s/%s", idx, bucket, part_key)
        part_keys.append(part_key)

    # Build manifest
    manifest = _build_manifest(internal_id, original_name, part_keys)
    manifest_key = f"manifests/{internal_id}.json"
    _update_status(bucket, internal_id, original_name, stage="split", total_parts=len(part_keys), manifest_key=manifest_key)
    _put_json(bucket, manifest_key, manifest)
    log.info("[Manifest] written to s3://%s/%s", bucket, manifest_key)

    # Transcribe (שימוש במזהה החדש)
    _update_status(bucket, internal_id, original_name, stage="transcribe_in_progress", total_parts=len(part_keys))
    results, errors = [], []
    max_workers = min(8, len(part_keys)) or 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(_transcribe_part, bucket, internal_id, k, idx): idx
                         for idx, k in enumerate(part_keys)}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            k = part_keys[idx]
            try:
                res = future.result()
                results.append(res)
                _update_status(bucket, internal_id, original_name,
                               stage="transcribe_in_progress",
                               completed_parts=len(results),
                               last_completed=k)
            except Exception as e:
                errors.append({"part_key": k, "error": str(e)})
                _update_status(bucket, internal_id, original_name,
                               stage="transcribe_in_progress",
                               error_for=k,
                               error=str(e))

    if errors:
        _update_status(bucket, internal_id, original_name, stage="transcribe_failed", errors=errors)
        raise RuntimeError(f"Transcribe failed: {errors}")

    _update_status(bucket, internal_id, original_name, stage="transcribe_completed", completed_parts=len(results))

    # Merge transcripts (עדיין לפי internal_id)
    texts = [r["text"] for r in sorted(results, key=lambda r: r["part_key"])]
    full_text = "\n".join(texts)
    merged_payload = {"internal_id": internal_id,
                      "original_name": original_name,
                      "parts": [r["part_key"] for r in sorted(results, key=lambda r: r["part_key"])],
                      "text": full_text}
    merged_key = f"transcriptions/{internal_id}/merged.json"
    _put_json(bucket, merged_key, merged_payload)
    _update_status(bucket, internal_id, original_name, stage="merged", merged_key=merged_key)

    # Summarize (שימוש בשם המקורי לסיכום)
    summary = _gemini_summarize_and_answer(full_text)
    out_key = f"{OUTPUT_PREFIX}{original_name}.summary.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=out_key,
        Body=json.dumps(summary, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json"
    )
    _update_status(bucket, internal_id, original_name, stage="summarized", summary_key=out_key)

    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok",
                            "summary_key": out_key,
                            "manifest_key": manifest_key,
                            "internal_id": internal_id,
                            "original_name": original_name}, ensure_ascii=False)
    }





def _find_internal_id_by_original(bucket: str, original_name: str) -> str | None:
    """
    חיפוש internal_id בקבצי statuses/ או manifests/ לפי original_name.
    מאפשר ל-Frontend לשלוח fileName בלבד, והפונקציה תמצא את ה-ID הפנימי.
    """
    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix="statuses/")
        for obj in response.get("Contents", []):
            key = obj["Key"]
            status_obj = s3_client.get_object(Bucket=bucket, Key=key)
            status_data = json.loads(status_obj["Body"].read().decode("utf-8"))
            if status_data.get("original_name") == original_name:
                return status_data.get("internal_id")
    except Exception as e:
        log.warning("Failed scanning statuses: %s", e)

    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix="manifests/")
        for obj in response.get("Contents", []):
            key = obj["Key"]
            manifest_obj = s3_client.get_object(Bucket=bucket, Key=key)
            manifest_data = json.loads(manifest_obj["Body"].read().decode("utf-8"))
            if manifest_data.get("original_name") == original_name:
                return manifest_data.get("internal_id")
    except Exception as e:
        log.warning("Failed scanning manifests: %s", e)

    return None


def summary_handler(event, context):
    """
    מחזיר סיכום אם הוא מוכן, אחרת מחזיר סטטוס התקדמות.
    תומך גם בפרמטר id (internal_id) וגם בפרמטר fileName (original_name).
    אם נשלח fileName בלבד, הפונקציה תמצא את ה-internal_id המתאים לפי statuses/manifests.
    """

    params = event.get("queryStringParameters") or {}
    file_name = params.get("fileName")
    internal_id = params.get("id")

    # אם לא נשלח id אבל יש fileName – ננסה למצוא internal_id לפי original_name
    if not internal_id and file_name:
        base_name = file_name.rsplit(".", 1)[0]
        internal_id = _find_internal_id_by_original(INPUT_BUCKET_NAME, base_name)

    if not internal_id:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "No status or manifest found for given file"})
        }

    status_key = f"statuses/{internal_id}.json"
    manifest_key = f"manifests/{internal_id}.json"

    # קודם ננסה להחזיר את הסיכום אם הוא מוכן
    try:
        status_obj = s3_client.get_object(Bucket=INPUT_BUCKET_NAME, Key=status_key)
        status_data = json.loads(status_obj["Body"].read().decode("utf-8"))
        summary_key = status_data.get("summary_key")
        if summary_key:
            obj = s3_client.get_object(Bucket=INPUT_BUCKET_NAME, Key=summary_key)
            body = obj["Body"].read().decode("utf-8")
            log.info("[SummaryHandler] summary found at s3://%s/%s", INPUT_BUCKET_NAME, summary_key)
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": body
            }
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchKey":
            log.error("[SummaryHandler] error reading summary: %s", e)
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)})
            }
        log.info("[SummaryHandler] summary not found yet, checking status")

    # אם אין סיכום עדיין – נחזיר סטטוס התקדמות
    try:
        status_obj = s3_client.get_object(Bucket=INPUT_BUCKET_NAME, Key=status_key)
        status_data = json.loads(status_obj["Body"].read().decode("utf-8"))
        log.info("[SummaryHandler] status loaded successfully: %s", status_data)

        # ננסה להעשיר את הנתונים עם manifest כדי לדעת כמה חלקים יש
        try:
            manifest_obj = s3_client.get_object(Bucket=INPUT_BUCKET_NAME, Key=manifest_key)
            manifest_data = json.loads(manifest_obj["Body"].read().decode("utf-8"))
            status_data["total_parts"] = manifest_data.get("total_parts")
        except ClientError:
            pass

        if status_data.get("stage") in ("transcribe_failed", "convert_failed", "preprocess_failed") or "errors" in status_data:
            log.error("[SummaryHandler] processing failed: %s", status_data.get("errors"))
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "error": "Processing failed",
                    "details": status_data.get("errors", []),
                    "stage": status_data.get("stage"),
                    "attempts": status_data.get("attempts")
                }, ensure_ascii=False)
            }

        # אחרת נחזיר דוח התקדמות
        return {
            "statusCode": 202,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "in-progress",
                "stage": status_data.get("stage"),
                "total_parts": status_data.get("total_parts"),
                "completed_parts": status_data.get("completed_parts"),
                "updated_at": status_data.get("updated_at"),
                "last_completed": status_data.get("last_completed"),
                "error_for": status_data.get("error_for"),
                "attempts": status_data.get("attempts"),
                "errors": status_data.get("errors"),
                "original_name": status_data.get("original_name"),
                "internal_id": status_data.get("internal_id")
            }, ensure_ascii=False)
        }

    except Exception as e:
        log.exception("[SummaryHandler] Unexpected error while reading status")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)})
        }



