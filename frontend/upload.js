// This URL is printed by `sam deploy` as Output: UploadApiUrl
const PRESIGN_ENDPOINT = "https://<your-api-id>.execute-api.<region>.amazonaws.com/presign";

const fileInput = document.getElementById('file-upload');
const uploadBtn = document.getElementById('upload-btn');
const statusMessage = document.getElementById('status-message');

function updateStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.style.color = isError ? 'red' : 'green';
}

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) {
    updateStatus("Please select an audio file.", true);
    return;
  }

  try {
    updateStatus(`1/2: Requesting pre-signed URL for ${file.name}...`);
    const resp = await fetch(PRESIGN_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fileName: file.name })
    });
    if (!resp.ok) {
      const errorBody = await resp.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(`Failed to get pre-signed URL: ${resp.status} ${errorBody.error}`);
    }
    const data = await resp.json();
    const uploadUrl = data.uploadUrl;

    updateStatus("2/2: Uploading file directly to S3...");
    const putResp = await fetch(uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file
    });
    if (!putResp.ok) throw new Error(`S3 upload failed: ${putResp.status}`);

    updateStatus("Upload successful! Processing will start automatically.");
  } catch (err) {
    console.error(err);
    updateStatus(`Upload failed: ${err.message}`, true);
  }
});
