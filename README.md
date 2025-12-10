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

**Status:** FUNCTIONING prototype. Core flows (presign, S3 triggers, summary API) are implemented. Full end-to-end integration (Transcribe → Gemini) and robust error handling are in progress.

---

## 🔑 Prerequisites

- **Python 3.12**  
- **AWS CLI** with permissions for CloudFormation, Lambda, S3, Transcribe, Secrets Manager  
- **AWS SAM CLI** (`sam --version`) for build/deploy and local testing  
- **Docker** — required if you want to build Lambda layers that are compatible with Amazon Linux (via `build-layer.ps1` or the Linux/macOS shell equivalent).  
- **Google AI Studio API Key** (Gemini), stored in **AWS Secrets Manager**  
- `requirements.txt` lists Python dependencies. For deployment in the cloud you must either:  
  - Install them locally so SAM can package them into the Lambda function, **or**  
  - Build a ready‑to‑use `layer.zip` with Docker that already contains the installed dependencies and binaries.  

> <small>⚠️ *Note: There is no option for a full local end‑to‑end test because the workflow depends on AWS services (Amazon Transcribe and Google Gemini). Dependencies must be prepared for the cloud runtime before deployment.*</small>

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

### 3. Install dependencies (for local development only)
```bash
pip install -r requirements.txt
```
⚠️ Note: Installing dependencies locally is only for running helper scripts or limited local testing. For deployment in the cloud, you must either let SAM package the dependencies during build, or create a Lambda Layer (recommended) that contains all required Python packages and binaries compiled against Amazon Linux.
---

## 📦 Lambda Layer Dependencies
AWS Lambda runs on **Amazon Linux**, which means Python packages and native binaries must be built in an environment that matches Lambda’s runtime.
To ensure compatibility, dependencies and tools (like `ffmpeg` and `ffprobe`) should be packaged into a **Lambda Layer** using Docker.

---

### 🔨 Building the Layer with `build-layer.ps1`

A helper script `build-layer.ps1` is included to automate the process of creating a Lambda layer that contains:

- **Python dependencies** from `requirements.txt`  
- **Static binaries** for `ffmpeg` and `ffprobe`  
- A packaged `layer.zip` ready to upload and attach to your Lambda functions  

#### What the script does:
1. Cleans old build artifacts (`layer/python`, `layer/bin`).  
2. Ensures **Docker Desktop** is running.  
3. Uses the official **Amazon Linux + Python 3.12 build image** to install Python dependencies into the correct path (`layer/python/lib/python3.12/site-packages`).  
4. Downloads static builds of `ffmpeg` and `ffprobe` and places them in `layer/bin`.  
5. Compresses everything into `layer.zip`.  
6. Stops Docker containers and Docker Desktop when finished.

---

### ▶️ Usage on Windows

Run the script in PowerShell:

```powershell
.\build-layer.ps1
```
### ▶️ Usage on Linux/macOS
You can replicate the same process with Docker commands in a shell script. 
See the 📦 Lambda Layer Dependencies section for details.
```Code
This corrected version makes it clear that:
- Local `pip install` is **only for development scripts**.  
- For cloud deployment, you need either SAM packaging or a **prebuilt Lambda layer**.  
- The `build-layer.ps1` script (or Linux/macOS equivalent) is the recommended way to prepare a `layer.zip` for AWS Lambda.  
```
---

## 🧪 Testing & Local Limitations

> <small>⚠️ *Important: A full local end‑to‑end run is not possible because the workflow depends on cloud services (Amazon Transcribe + Google Gemini). You can only test parts locally:*  
> - **Frontend locally → Cloud backend**  
> - **Individual Lambda handlers** with SAM Local (unit testing only, no external services emulation)*</small>

---

## ☁️ Deployment

You can deploy manually with SAM or use the automation script `deploy_full.py`.

> <small>⚠️ *Notes:*  
> - You will **always need to update the Lambda template (`template.yaml`)** with your own unique resource names:  
>   - A custom **secret name** in AWS Secrets Manager for the Gemini API key.  
>   - Unique **S3 bucket names** for artifacts, input, and output (bucket names must be globally unique).  
> - The automation script (`deploy_full.py`) will **automatically delete any existing cloud resources (including buckets and stacks) with the chosen names before redeployment**, and then recreate them to ensure a clean environment.  
> - Deployment must be run with a user that has **Administrator permissions**. Make sure you are logged in with an admin profile before running the script.  
> - Example run:  
>   ```bash
>   py deploy_full.py --profile admin-manager --region us-east-1
>   ```  
> - If you choose to deploy manually (without the script), you must create the required S3 buckets in advance, configure **static website hosting** for the frontend bucket, and attach the necessary **bucket policies and CORS rules** yourself.*</small>

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

- **API 500 errors**  
  Check Lambda logs in CloudWatch to identify stack traces and errors.

- **Missing summary (404)**  
  Verify that the summary Lambda completed successfully and wrote the output file to:  
  `summaries/<file>.summary.json`

- **CORS issues**  
  Configure S3 bucket CORS or API Gateway CORS to allow cross‑origin requests.

- **Permissions**  
  Ensure the Lambda execution role includes:  
  - S3 read/write  
  - Transcribe start/get  
  - Secrets Manager read  
  - CloudWatch logs  

- **Layer empty after build**  
  Confirm `build-layer.ps1` or the Linux/macOS build script ran successfully.  
  Check that:  
  - `layer/python/lib/python3.12/site-packages` contains Python packages  
  - `layer/bin` contains `ffmpeg` and `ffprobe`
---

## ✅ Final Notes

- Audio files are **uploaded securely** to S3.  
- Processing is **parallelized** — multiple audio files can be transcribed and summarized simultaneously.  
- Summaries are stored in S3 and exposed via API.  
- Full integration testing requires deployment to AWS with a valid Gemini key.
- To save costs, you can remove all deployed resources with the cleanup script:
    ```bash
    python delete_all_resources.py --profile admin-manager --region us-east-1
    ```

