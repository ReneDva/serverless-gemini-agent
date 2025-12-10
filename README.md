# 🤖 Serverless Gemini Agent

![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)  
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)  
![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=googlebard&logoColor=white)

**A serverless prototype using AWS Lambda and Google Gemini to analyze and summarize audio content.**

---

## 📌 Overview

This repository demonstrates a **serverless, event-driven pipeline** for audio analysis:

- **Client Upload:** Audio files are uploaded securely via pre-signed S3 URLs.  
- **Parallel Processing:** Each upload triggers a Lambda that starts **Amazon Transcribe** jobs. Multiple audio files can be processed **concurrently**.  
- **Summarization:** Once transcription is complete, results are merged and sent to **Google Gemini** for structured summaries.  
- **Storage & Access:** Summaries are written back to S3 and exposed via an HTTP API for retrieval.

**Status:** Early prototype. Core flows (presign, S3 triggers, summary API) are implemented. Full end-to-end integration (Transcribe → Gemini) and robust error handling are in progress.

---

## 🔑 Prerequisites

- **Python 3.12+**  
- **AWS CLI** with permissions for CloudFormation, Lambda, S3, Transcribe, Secrets Manager  
- **AWS SAM CLI** (`sam --version`) for build/deploy and local testing  
- **Docker** (optional) for container-based builds  
- **Google AI Studio API Key** (Gemini), stored in **AWS Secrets Manager**  
- `requirements.txt` lists Python dependencies for Lambdas and layers  

---

## 🚀 Quickstart

### 1. Clone the repository
```bash
git clone https://github.com/ReneDva/serverless-gemini-agent.git
cd serverless-gemini-agent
```

### 2. Create and activate virtual environment
```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
.\.venv\Scripts\Activate.ps1 # Windows PowerShell
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

---

## 🧪 Testing & Local Limitations

⚠️ **Important:** A full local end-to-end run is **not possible** because the workflow depends on cloud services (Amazon Transcribe + Google Gemini). You can test parts locally:

- **Frontend locally → Cloud backend**  
- **Individual Lambda handlers** with SAM Local (unit testing only, no external services emulation)

---
## ☁️ Deployment

You can deploy manually with SAM or use the automation script `deploy_full.py`.

> ⚠️ **Note:**  
> - If you choose to deploy manually (without using the provided automation script), you must create the required **S3 buckets** in advance (for artifacts, input, and output).  
> - After deployment, configure **static website hosting** for the frontend bucket and attach the necessary **bucket policies and CORS rules**.  
> - You also need to **update the Lambda template (`template.yaml`)** with the correct **secret name** (matching the one you created in AWS Secrets Manager) and adjust the **default environment variables** to ensure the functions can access the Gemini API key and other configuration values.

### Example `samconfig.toml`
```toml
version = 0.1

[default.deploy.parameters]
profile = "admin-manager"
stack_name = "rene-gemini-agent-stack-dev"
s3_bucket = "rene-sam-artifacts-bucket"
s3_prefix = "rene-gemini-agent-stack-dev"
region = "us-east-1"
confirm_changeset = false
capabilities = "CAPABILITY_IAM"
disable_rollback = true
parameter_overrides = "InputBucketName=\"rene-gemini-agent-user-input-2025\" GeminiSecretName=\"my/gemini/all-env\" OutputPrefix=\"summaries/\" TranscribeRegion=\"us-east-1\" TranscribeLanguage=\"he-IL\" GeminiModel=\"gemini-2.5-flash\""
image_repositories = []

[default.global.parameters]
region = "us-east-1"
```

---

## 🔐 Secrets Management

Store your Gemini API key in **AWS Secrets Manager**:

```json
{
  "GEMINI_API_KEY": "your_gemini_api_key_here"
}
```

Upload with:
```bash
python save_to_secrets.py --secrets-file secrets_gemini.json --secret-name my/gemini/all-env --region us-east-1
```

---

## 🌐 Frontend Hosting

- Upload frontend files (HTML, CSS, JS) to an S3 bucket configured for static website hosting.  
- Use **CloudFront** for HTTPS, caching, and global distribution.  
- Ensure fonts support Hebrew for PDF generation.  

---

## 🛠️ Troubleshooting

- **API 500 errors:** Check Lambda logs in CloudWatch.  
- **Missing summary (404):** Verify the summary Lambda completed and wrote to `summaries/<file>.summary.json`.  
- **CORS issues:** Configure S3 bucket CORS or API Gateway CORS.  
- **Permissions:** Ensure Lambda roles include S3 read/write, Transcribe start/get, Secrets Manager read, CloudWatch logs.  

---

## ✅ Final Notes

- Audio files are **uploaded securely** to S3.  
- Processing is **parallelized** — multiple audio files can be transcribed and summarized simultaneously.  
- Summaries are stored in S3 and exposed via API.  
- Full integration testing requires deployment to AWS with a valid Gemini key.  

