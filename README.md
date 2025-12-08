# 🤖 Serverless Gemini Agent

![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=googlebard&logoColor=white)

**A serverless prototype that uses AWS Lambda and Google Gemini to analyze and summarize audio content.**

---

### Overview

This repository demonstrates a serverless, event-driven pipeline:

- **Client** uploads audio via a pre-signed S3 URL.  
- **S3** upload triggers a Lambda that starts transcription (Amazon Transcribe), merges results and calls **Google Gemini** for structured summaries.  
- Summaries are written back to S3 and exposed via an HTTP API.

**Status:** early prototype. Core pieces (presign flow, S3 triggers, summary API) are implemented; end-to-end Transcribe → Gemini integration and hardened error handling are in progress.

Contributions, feedback and PRs are welcome (architecture, security, deployment improvements).

---

## Prerequisites

- **Python 3.12+**  
- **AWS CLI** configured with a profile that has permissions for CloudFormation, Lambda, S3, Transcribe and Secrets Manager.  
- **AWS SAM CLI** (`sam --version`) for build/deploy and local testing.  
- **Docker** (optional) for `sam build --use-container` and for building the Lambda layer.  
- **Google AI Studio API Key** (Gemini) — stored in AWS Secrets Manager (recommended).  
- `requirements.txt` lists Python dependencies used by Lambdas and the layer.

---

## Quickstart

### 1. Clone repository
```bash
git clone https://github.com/ReneDva/serverless-gemini-agent.git
cd serverless-gemini-agent
```

### 2. Create and activate virtualenv (optional for local scripts)
```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate
```

### 3. Install local dev dependencies
```bash
pip install -r requirements.txt
```

---

## Testing and Local Limitations

**Important:** a full local end-to-end run is **not possible** because the workflow depends on cloud services (Amazon Transcribe and Google Gemini). You can perform partial/local checks:

### Local frontend against cloud backend
Run the frontend locally and point it to the deployed API endpoints:
```powershell
cd frontend
python -m http.server 5500
# open http://localhost:5500/frontend/index.html
```
Ensure your frontend config points to the cloud endpoints:
```javascript
const isLocal = false; // use cloud endpoints
```

### Local backend function testing (limited)
You can invoke individual Lambda handlers locally for unit testing or debugging with SAM Local, but this **does not** emulate external cloud services:
```powershell
sam build --use-container
sam local invoke PresignFunction --event events/PresignRequest.json --env-vars env.json
sam local invoke VoiceAgentFunction --event events/TestTranscribeStarter.json --env-vars env.json
```
Use these local runs to validate input/output shapes and basic logic. For full integration tests, deploy to AWS.

---

## Deployment and Configuration

You can deploy manually with SAM or use the provided automation script `deploy_full.py` which packages, deploys and uploads the frontend.

### samconfig.toml
Instead of `sam deploy --guided`, preconfigure `samconfig.toml` so deploys are non-interactive. Example:
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

Edit `parameter_overrides` or `template.yaml` parameters before deploy to set:
- `InputBucketName`
- `GeminiSecretName`
- `OutputPrefix`
- `TranscribeRegion`
- `TranscribeLanguage`
- `GeminiModel`

### Secrets Manager for Gemini API key
Create a JSON file `secrets_gemini.json`:
```json
{
  "GEMINI_API_KEY": "your_gemini_api_key_here"
}
```
Use the included script to upload (it force-deletes any existing secret with the same name, waits for name to free, then creates the secret):

```bash
python save_to_secrets.py --secrets-file secrets_gemini.json --secret-name my/gemini/all-env --region us-east-1
```

### Deploy with SAM (manual)
1. Build:
```powershell
sam build
```
2. Ensure artifacts bucket exists:
```powershell
aws s3 mb s3://rene-sam-artifacts-bucket --region us-east-1
```
3. Deploy (uses `samconfig.toml` if present):
```powershell
sam deploy
```

### Automated deploy script
`deploy_full.py` automates:
- optional cleanup of previous resources,
- recreating artifacts bucket,
- `sam build` and `sam deploy`,
- patching `frontend/upload.js` with API endpoints,
- uploading selected frontend files to the input bucket,
- configuring the bucket as a static website.

Example:
```bash
py deploy_full.py --profile admin-manager --region us-east-1
```

### Frontend hosting
Recommended production setup:
- Upload frontend files (HTML, CSS, JS, fonts) to an S3 bucket configured for static website hosting.
- Front the bucket with CloudFront for HTTPS, caching and global distribution.
- Ensure fonts that support Hebrew are included for PDF generation.

---

## Troubleshooting and Logs

- **API 500 errors**: check Lambda CloudWatch logs for stack traces. Use:
```bash
aws logs tail /aws/lambda/<FunctionName> --follow --profile admin-manager
```
- **Missing summary (404)**: the summary file may not be ready; verify the Lambda that produces it completed successfully and wrote to `summaries/<file>.summary.json` in the input bucket.
- **CORS issues**: ensure S3 bucket CORS is configured (or use API Gateway CORS). Example `cors.json` used with `aws s3api put-bucket-cors`.
- **Layer empty after build**: confirm `build-layer.ps1` ran successfully and that `layer/python/lib/python3.12/site-packages` contains packages. Use Docker logs and the script debug output.
- **Permissions**: Lambda execution role must include S3 read/write, Transcribe start/get, Secrets Manager read, and CloudWatch logs permissions.

---

### Final Notes

- **No full local end-to-end run**: because the pipeline depends on managed cloud services (Transcribe, Gemini), full integration tests require deployment to AWS and a valid Gemini key in Secrets Manager.  
- **Iterate safely**: use `samconfig.toml` and `save_to_secrets.py` to automate repeatable deployments. Use `deploy_full.py` for convenience when you want a clean redeploy and frontend upload.




















# 🤖 Serverless Gemini Agent

![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=googlebard&logoColor=white)

**A Serverless Prototype utilizing AWS Lambda and Google's Gemini Pro model to analyze and summarize audio content.**

---

### 🚀 Project Status: Early Prototype & Initial Setup (WIP) 🚧

This project is currently focused on **establishing core foundational components** of a robust, event-driven architecture on AWS Lambda.

We have successfully implemented and are testing:
1. **Client-side upload mechanism** via a Pre-Signed URL generator.
2. **Initial Serverless Functions** for file handling and job initiation.

The **full end-to-end workflow (Transcribe → Gemini)** is currently being connected and validated. Work is ongoing on error handling and securing all service integrations.

---

## 🌟 Contributions and Feedback

This project is **open to constructive criticism and suggestions**, as we are still evaluating the most effective and cost-efficient way to link the different services.

| Area of Focus | Seeking Feedback On... |
| :--- | :--- |
| **Architecture & Workflow** | Best practices for linking services asynchronously (e.g., SQS/SNS vs. S3 triggers). |
| **Security & Best Practices** | Secure API key management (e.g., AWS Secrets Manager instead of Environment Variables). |
| **Error Handling** | Strategies for handling failures (e.g., S3 upload errors, Transcribe job start errors). |
| **Deployment** | Standardizing deployment with **AWS SAM** or **Serverless Framework**. |

---

## 📖 About The Project

This project demonstrates how to build a cost-effective, serverless AI application.  
The system automatically triggers when a file (text or transcript) is uploaded to an AWS S3 bucket. It processes the content using the Google Gemini API and saves the analysis (summary/insights) back to S3.

### Key Features
* **Serverless Architecture:** Built on AWS Lambda (Zero idle costs).
* **Event-Driven:** Automatically triggered by S3 file uploads.
* **GenAI Integration:** Uses Google Gemini for advanced natural language processing.
* **Secure:** Environment Variables for API key management.

---

## 🏗️ Architecture & Workflow

1. **Upload:** A user uploads a file (e.g., `meeting-notes.txt`) to the **Input S3 Bucket**.
2. **Trigger:** The upload event triggers an **AWS Lambda** function.
3. **Process:**
   * The Lambda function reads the file content.
   * It sends the content + a prompt to **Google Gemini**.
4. **Output:** The generated summary/answer is saved as a new file in the **Output S3 Bucket**.

---

## 🛠️ Tech Stack

* **Cloud Provider:** AWS (Amazon Web Services)
* **Compute:** AWS Lambda (Python 3.x Runtime)
* **Storage:** Amazon S3
* **AI Model:** Google Gemini API (via `google-genai` SDK)
* **Infrastructure:** AWS SDK for Python (`boto3`)

---

## 🚀 Getting Started

### Prerequisites

* **Python 3.12+** installed.
* **AWS CLI** configured with appropriate permissions.
* **AWS SAM CLI** installed (`sam --version` to verify).
* **Docker** (optional, for full emulation).
* **Google AI Studio API Key** ([Get it here](https://aistudio.google.com/)).

---

### 1. Clone the Repository

```bash
git clone https://github.com/ReneDva/serverless-gemini-agent.git
cd serverless-gemini-agent
```

### 2. Installing AWS SAM CLI
Windows
```bash
winget install --id Amazon.SAM-CLI -e
```
Or download and run the official MSI from the AWS SAM releases page:
https://github.com/aws/aws-sam-cli/releases
After install, open a new terminal and verify:
```bash
sam --version
```
### macOS

```bash
brew tap aws/tap
brew install aws-sam-cli
sam --version
```

### Linux
Use the official installer from AWS (see releases) or package manager if available.
Example using pipx (not official installer but works for many setups):
```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
pipx install aws-sam-cli
sam --version
```

## 🧪 Testing & Running the Project

ניתן לבצע בדיקות בשתי דרכים עיקריות:

- **הרצה מלאה בענן** – פריסת ה־Backend עם AWS SAM ופריסת ה־Frontend כאתר סטטי ב־S3 + CloudFront.  
- **הרצה מקומית של הפרונט** – הרצת ה־Frontend מקומית מול Backend שכבר פרוס בענן.

> ⚠️ חשוב: הרצה מקומית מלאה של כל המערכת אינה אפשרית, מאחר שהפרויקט תלוי בשירותי צד ג' בענן (Amazon Transcribe, Google Gemini).  
> ניתן לבדוק מקומית רק את ה־Frontend, או להריץ פונקציות בודדות עם SAM Local לצורך דיבאג, אך לא את כל ה־Workflow.

---

### 🔹 בדיקה מקומית של הפרונט מול Backend בענן

```powershell
cd C:\serverless-gemini-agent
python -m http.server 5500
```

גש לכתובת: http://localhost:5500/frontend/index.html

ודא שבקובץ ה־JS שלך (למשל `app.js`) מוגדר:
```javascript
const isLocal = false;
```
כך שהקריאות יופנו ל־API בענן ולא ל־localhost.

---

## 🚀 פריסה מלאה בענן

לצורך פריסה מלאה בענן ניתן להשתמש בסקריפט `deploy_full.py` שמבצע את כל השלבים באופן אוטומטי, כולל מחיקת אובייקטים וסטאקים ישנים מריצות קודמות.  
הסקריפט מריץ את הבנייה, הפריסה, עדכון קובץ ה־frontend עם כתובות ה־API החדשות, והעלאת קבצי ה־frontend ל־S3 כאתר סטטי.

### Backend (AWS SAM)

בנייה:
```powershell
sam build
```

יצירת דלי לארטיפקטים:
```powershell
aws s3 mb s3://rene-sam-artifacts-bucket --region us-east-1
```

פריסה:
```powershell
sam deploy --guided --s3-bucket rene-sam-artifacts-bucket
```

### Frontend (S3 + CloudFront)

- העלה את קבצי ה־frontend (HTML, CSS, JS) ל־S3 כאתר סטטי.  
- הוסף CloudFront להפצה גלובלית עם CDN.  
- זה הפתרון הנפוץ ביותר ל־frontend סטטי.

---

### ✅ סיכום

- **אין אפשרות להריץ מקומית את כל המערכת** – השירותים החיצוניים דורשים ענן.  
- **בדיקה מקומית אפשרית רק לפרונט** מול Backend בענן.  
- **פריסה מלאה** מתבצעת בענן: SAM Deploy ל־Backend + S3/CloudFront ל־Frontend.  

## 🚀 פריסה מלאה בענן עם קובץ samconfig.toml והגדרת סודות

במקום להריץ `sam deploy --guided` בכל פעם, ניתן להגדיר מראש את קובץ **`samconfig.toml`** עם כל הפרמטרים הדרושים.  
כך הפריסה מתבצעת אוטומטית ללא צורך בהקלדת ערכים ידנית.

### samconfig.toml
דוגמה לקובץ מוגדר מראש:
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

### Environment Variables
Some tests require environment variables. Generate env.json with:

