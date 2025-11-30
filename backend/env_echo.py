import os
import json

def handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({"GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
                            "ALL_ENV": {k: v for k, v in os.environ.items() if k in {
                                "GEMINI_API_KEY","INPUT_BUCKET_NAME","OUTPUT_PREFIX","TRANSCRIBE_REGION","TRANSCRIBE_LANGUAGE","GEMINI_MODEL","REAL_CLOUD","AUDIO_PATH"}}})
    }
