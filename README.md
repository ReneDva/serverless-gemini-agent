# 🤖 Serverless Gemini Agent

![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=googlebard&logoColor=white)

**A serverless automated agent built on AWS Lambda that utilizes Google's Gemini Pro model to analyze, summarize, and answer questions about uploaded content.**

---

## 📖 About The Project

This project demonstrates how to build a cost-effective, serverless AI application. The system automatically triggers when a file (text or transcript) is uploaded to an AWS S3 bucket. It processes the content using the Google Gemini API and saves the analysis (summary/insights) back to S3.

### Key Features
* **Serverless Architecture:** Built on AWS Lambda (Zero idle costs).
* **Event-Driven:** Automatically triggered by S3 file uploads.
* **GenAI Integration:** Uses Google Gemini for advanced natural language processing.
* **Secure:** Uses Environment Variables for API key management.

---

## 🏗️ Architecture & Workflow

1.  **Upload:** A user uploads a file (e.g., `meeting-notes.txt`) to the **Input S3 Bucket**.
2.  **Trigger:** The upload event triggers an **AWS Lambda** function.
3.  **Process:**
    * The Lambda function reads the file content.
    * It sends the content + a prompt to **Google Gemini**.
4.  **Output:** The generated summary/answer is saved as a new file in the **Output S3 Bucket**.

---

## 🛠️ Tech Stack

* **Cloud Provider:** AWS (Amazon Web Services)
* **Compute:** AWS Lambda (Python 3.x Runtime)
* **Storage:** Amazon S3
* **AI Model:** Google Gemini API (via `google-genai` SDK)
* **Infrastructure:** AWS SDK for Python (`boto3`)

---

## 🚀 Getting Started

Follow these steps to set up the project locally and deploy it to AWS.

### Prerequisites

* **Python 3.9+** installed.
* **AWS CLI** configured with appropriate permissions.
* **Google AI Studio API Key** ([Get it here](https://aistudio.google.com/)).

### 1. Clone the Repository

```bash
git clone [https://github.com/your-username/serverless-gemini-agent.git](https://github.com/your-username/serverless-gemini-agent.git)
cd serverless-gemini-agent