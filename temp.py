import requests

url = "https://rene-gemini-agent-user-input-2025.s3.amazonaws.com/user_recording_123.m4a?AWSAccessKeyId=AKIA3477ESLCN7UQBFXV&Signature=j52QF%2BykKqfYOdO7S0qk346XM%2F8%3D&content-type=application%2Foctet-stream&Expires=1764600096"
file_path = r"C:\serverless-gemini-agent\uploads\user_recording_123.m4a"

with open(file_path, "rb") as f:
    resp = requests.put(url, data=f, headers={"Content-Type": "audio/m4a"})

print(resp.status_code)
print(resp.text)
