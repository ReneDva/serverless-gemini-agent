# 🤖 Serverless Gemini Agent

![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=googlebard&logoColor=white)

**A Serverless Prototype utilizing AWS Lambda and Google's Gemini Pro model to analyze and summarize audio content.**

### 🚀 Project Status: Early Prototype & Initial Setup (WIP) 🚧

This project is currently focused on **establishing core foundational components** of a robust, event-driven architecture on AWS Lambda.

We have successfully implemented and are testing:
1.  **Client-side upload mechanism** via a Pre-Signed URL generator.
2.  **Initial Serverless Functions** for file handling and job initiation.

The **full end-to-end workflow (Transcribe $\rightarrow$ Gemini)** is currently being connected and validated. We are working on comprehensive error handling and securing all service integrations.

---

## 🌟 Contributions and Feedback

This project is **open to constructive criticism and suggestions**, as we are still evaluating the most effective and cost-efficient way to link the different services.

| Area of Focus | Seeking Feedback On... |
| :--- | :--- |
| **Architecture & Workflow** | Best practices for **linking the services asynchronously** (e.g., using SQS/SNS vs. S3 triggers) now that the components are separate. |
| **Security & Best Practices** | Recommendations for securely managing API keys (e.g., migrating from Environment Variables to **AWS Secrets Manager**). |
| **Error Handling** | Basic strategies for handling initial points of failure (e.g., S3 upload failures or initial Transcribe job start errors). |
| **Deployment** | Suggestions for standardizing the deployment process using **AWS SAM** or the **Serverless Framework** as we move beyond the AWS Console. |

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
git clone [https://github.com/ReneDva/serverless-gemini-agent.git](https://github.com/your-username/serverless-gemini-agent.git)

cd serverless-gemini-agent

