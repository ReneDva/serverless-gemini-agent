// *** CRITICAL: REPLACE WITH YOUR ACTUAL LAMBDA FUNCTION URL ***
const PRE_SIGN_URL_GENERATOR_URL = "https://<your-presign-lambda-id>.lambda-url.eu-north-1.on.aws";

const fileInput = document.getElementById('file-upload');
const statusMessage = document.getElementById('status-message');

function updateStatus(message, isError = false) {
    statusMessage.textContent = message;
    statusMessage.style.color = isError ? 'red' : 'green';
}

async function uploadAudio() {
    const file = fileInput.files[0];
    if (!file) {
        updateStatus("Please select an audio file.", true);
        return;
    }

    updateStatus(`1/2: Requesting pre-signed URL for ${file.name}...`);

    // --- שלב 1: קבלת הלינק המאובטח מה-Lambda Function URL ---
    try {
        const response = await fetch(PRE_SIGN_URL_GENERATOR_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ fileName: file.name })
        });

        if (!response.ok) {
            const errorBody = await response.json().catch(() => ({error: "Unknown error"}));
            throw new Error(`Failed to get pre-signed URL. Status: ${response.status}. Error: ${errorBody.error}`);
        }

        const data = await response.json();
        const uploadUrl = data.uploadUrl;

        updateStatus(`2/2: URL received. Uploading file directly to S3...`);

        // --- שלב 2: העלאה ישירה ל-S3 באמצעות הלינק ---
        const uploadResponse = await fetch(uploadUrl, {
            method: 'PUT',
            // חובה: ה-Content-Type חייב להתאים לזה שצוין כאשר נוצר ה-Pre-Signed URL (אם צוין)
            headers: { 'Content-Type': file.type || 'application/octet-stream' },
            body: file
        });

        if (uploadResponse.ok) {
            updateStatus("Upload successful! Processing has started by the Gemini Agent.");
        } else {
            updateStatus(`S3 upload failed. Status: ${uploadResponse.status}`, true);
        }

    } catch (error) {
        console.error("Upload process error:", error);
        updateStatus(`Upload failed: ${error.message}`, true);
    }
}