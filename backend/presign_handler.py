import os
import json
import boto3
from dotenv import load_dotenv

# טוען משתנים מקובץ .env מקומי לבדיקה
load_dotenv()

# השם של דלי הקלט/פלט שלך
INPUT_BUCKET_NAME = os.environ.get('INPUT_BUCKET_NAME')
s3_client = boto3.client('s3')


def presign_handler(event, context):
    """
    מטפל בקריאת API Gateway/Function URL ומחזיר URL מאובטח.
    """
    if not INPUT_BUCKET_NAME:
        return {'statusCode': 500, 'body': json.dumps("ERROR: INPUT_BUCKET_NAME not set.")}

    try:
        # משיכת שם הקובץ שצריך לעלות, או שימוש בברירת מחדל
        # בבדיקה מקומית נשתמש בשם קבוע, ב-API Gateway זה יגיע מה-JSON Body.
        try:
            body = json.loads(event.get('body', '{}'))
            file_name = body.get('fileName', 'uploaded_audio_test.mp3')
        except json.JSONDecodeError:
            file_name = 'uploaded_audio_test.mp3'

        # יצירת ה-URL המאובטח להעלאה (PUT)
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': INPUT_BUCKET_NAME,
                'Key': file_name
            },
            ExpiresIn=3600  # שעה אחת
        )

        return {
            'statusCode': 200,
            'body': json.dumps({'uploadUrl': presigned_url, 'fileKey': file_name})
        }

    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# --- הרצה מקומית (Local Runner) ---
if __name__ == "__main__":
    # מדמה בקשת POST מה-Frontend (שמבקשת להעלות קובץ)
    test_event = {
        "body": json.dumps({"fileName": "user_recording_123.wav"})
    }

    print("\n--- Testing PreSignUrlGenerator Locally ---")
    result = presign_handler(test_event, {})

    print("Pre-Signed URL Result:")
    print(result['body'])

    try:
        data = json.loads(result['body'])
        print(f"\nGenerated URL: {data['uploadUrl']}")
        print(f"File Key: {data['fileKey']}")
    except:
        pass
    print("-------------------------------------------\n")