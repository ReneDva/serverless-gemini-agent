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

## 🧪 Testing
### Local Testing (Before Cloud Deployment)
1. Install AWS SAM CLI 
   Official tool for local Lambda testing and deployment.
2. Run with Events 
   Use prepared JSON files in the events/ folder.
```bash
sam local invoke PresignFunction --event events/PresignRequest.json
sam local invoke VoiceAgentFunction --event events/TestTranscribeStarter.json
```
```json
{"statusCode":200,"headers":{"Content-Type":"application/json"},"body":"{\"uploadUrl\":\"https://s3.amazonaws.com/...\",\"fileKey\":\"user_recording_123.wav\"}"}

```

### Without Docker (Quick Python Test)
```bash
python backend/presign_handler.py events/PresignRequest.json
```
This does not emulate Lambda but provides a fast check.

### Cloud Testing
Instead of local emulation, deploy directly:
```bash
sam deploy
```
This offloads container execution to AWS.

### Build with Container
```bash
sam build --use-container
```
If issues occur, clear previous build:
```powershell
Remove-Item -Recurse -Force .aws-sam
sam build --use-container
```

### Environment Variables
Some tests require environment variables. Generate env.json with:

```powershell
.\Generate-EnvJson.ps1
```
Run with env vars:
```bash
sam local invoke VoiceAgentFunction --event events/TestTranscribeStarter.json --env-vars env.json
```
Debug mode:
```bash
sam local invoke VoiceAgentFunction --event events/TestTranscribeStarter.json --env-vars env.json --debug
```
✅ Summary
This documentation covers:
- Local testing with AWS SAM CLI. 
- Quick Python-based checks. 
- Cloud deployment testing. 
- Container builds and rebuilds. 
- Environment variable setup.

The project is ready for **iterative development, testing, and deployment**.