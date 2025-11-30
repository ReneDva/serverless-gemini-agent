// Detect environment based on hostname
const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

// Define endpoints accordingly
const PRESIGN_ENDPOINT = isLocal
  ? "http://127.0.0.1:3000/presign"
  : "https://<your-api-id>.execute-api.<region>.amazonaws.com/presign";

const SUMMARY_ENDPOINT = isLocal
  ? "http://127.0.0.1:3000/summary"
  : "https://<your-api-id>.execute-api.<region>.amazonaws.com/summary";

const fileInput = document.getElementById('file-upload');
const uploadBtn = document.getElementById('upload-btn');
const statusMessage = document.getElementById('status-message');
const summaryText = document.getElementById('summary-text');
const downloadBtn = document.getElementById('download-btn');

function updateStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.style.color = isError ? 'red' : 'green';
}

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) {
    updateStatus("אנא בחר קובץ שמע.", true);
    return;
  }

  try {
    updateStatus(`1/2: מבקש כתובת presign עבור ${file.name}...`);
    const resp = await fetch(PRESIGN_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fileName: file.name })
    });
    if (!resp.ok) {
      const errorBody = await resp.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(`נכשל בקבלת כתובת presign: ${resp.status} ${errorBody.error}`);
    }
    const data = await resp.json();
    const uploadUrl = data.uploadUrl;

    updateStatus("2/2: מעלה קובץ ישירות ל‑S3...");
    const putResp = await fetch(uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file
    });
    if (!putResp.ok) throw new Error(`העלאה ל‑S3 נכשלה: ${putResp.status}`);

    updateStatus("העלאה הצליחה! מתחיל עיבוד...");

    // Call summary endpoint to get transcript + summary
    const summaryResp = await fetch(`${SUMMARY_ENDPOINT}?fileName=${encodeURIComponent(file.name)}`);
    if (!summaryResp.ok) throw new Error(`נכשל בקבלת סיכום: ${summaryResp.status}`);
    const summaryData = await summaryResp.json();

    // Display transcript/summary nicely
    summaryText.textContent = JSON.stringify(summaryData, null, 2);

  } catch (err) {
    console.error(err);
    updateStatus(`העלאה נכשלה: ${err.message}`, true);
  }
});

// Download as PDF
downloadBtn.addEventListener('click', () => {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });
  doc.setFont("Helvetica", "normal");
  doc.setFontSize(12);
  doc.text(summaryText.textContent, 40, 60, { maxWidth: 500 });
  doc.save("summary.pdf");
});
