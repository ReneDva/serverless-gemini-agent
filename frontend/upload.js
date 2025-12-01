// Detect environment based on hostname
const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

console.log(">>> זיהוי סביבת הרצה:", isLocal ? "Local" : "Cloud");

const PRESIGN_ENDPOINT = isLocal
  ? "http://127.0.0.1:3000/presign"
  : "https://<your-api-id>.execute-api.<region>.amazonaws.com/presign";

const SUMMARY_ENDPOINT = isLocal
  ? "http://127.0.0.1:3000/summary"
  : "https://<your-api-id>.execute-api.<region>.amazonaws.com/summary";

console.log(">>> PRESIGN_ENDPOINT:", PRESIGN_ENDPOINT);
console.log(">>> SUMMARY_ENDPOINT:", SUMMARY_ENDPOINT);

const fileInput = document.getElementById('file-upload');
const uploadBtn = document.getElementById('upload-btn');
const statusMessage = document.getElementById('status-message');
const summaryText = document.getElementById('summary-text');
const downloadBtn = document.getElementById('download-btn');

function updateStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.style.color = isError ? 'red' : 'green';
  console.log(">>> עדכון סטטוס:", message, "שגיאה?", isError);
}

function resolveContentType(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  switch (ext) {
    case 'mp3': return 'audio/mpeg';
    case 'wav': return 'audio/wav';
    case 'm4a': return 'audio/m4a';
    case 'ogg': return 'audio/ogg';
    case 'flac': return 'audio/flac';
    default: return 'application/octet-stream';
  }
}

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) {
    updateStatus("אנא בחר קובץ שמע.", true);
    return;
  }

  try {
    const contentType = "application/octet-stream"; // אחידות
    console.log(">>> קובץ נבחר:", file.name, "גודל:", file.size, "סוג:", file.type);
    console.log(">>> Content-Type שנבחר להעלאה:", contentType);

    updateStatus(`1/2: מבקש כתובת presign עבור ${file.name}...`);
    console.log(">>> שולח בקשת presign ל:", PRESIGN_ENDPOINT);

    const resp = await fetch(PRESIGN_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fileName: file.name, contentType })
    });

    console.log(">>> תשובת presign התקבלה. סטטוס:", resp.status);

    if (!resp.ok) {
      const errorBody = await resp.text();
      console.error(">>> גוף שגיאה מהשרת:", errorBody);
      throw new Error(`נכשל בקבלת כתובת presign: ${resp.status} ${errorBody}`);
    }

    const data = await resp.json();
    console.log(">>> נתוני presign:", data);

    const uploadUrl = data.uploadUrl;
    console.log(">>> כתובת presigned URL להעלאה:", uploadUrl);

    updateStatus("2/2: מעלה קובץ ישירות ל‑S3...");
    console.log(">>> שולח PUT ל‑S3 עם Content-Type:", contentType);

    const putResp = await fetch(uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': contentType },
      body: file
    });

    console.log(">>> תשובת PUT התקבלה. סטטוס:", putResp.status);

    if (!putResp.ok) throw new Error(`העלאה ל‑S3 נכשלה: ${putResp.status}`);

    updateStatus("העלאה הצליחה! מתחיל עיבוד...");

    console.log(">>> שולח בקשת summary ל:", SUMMARY_ENDPOINT, "עם fileName:", file.name);

    const summaryResp = await fetch(`${SUMMARY_ENDPOINT}?fileName=${encodeURIComponent(file.name)}`);
    console.log(">>> תשובת summary התקבלה. סטטוס:", summaryResp.status);

    if (!summaryResp.ok) throw new Error(`נכשל בקבלת סיכום: ${summaryResp.status}`);
    const summaryData = await summaryResp.json();
    console.log(">>> נתוני summary:", summaryData);

    summaryText.textContent = JSON.stringify(summaryData, null, 2);

  } catch (err) {
    console.error(">>> שגיאה כללית:", err);
    updateStatus(`העלאה נכשלה: ${err.message}`, true);
  }
});

// Download as PDF
downloadBtn.addEventListener('click', () => {
  console.log(">>> התחלת יצירת PDF להורדה");
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });
  doc.setFont("Helvetica", "normal");
  doc.setFontSize(12);
  doc.text(summaryText.textContent, 40, 60, { maxWidth: 500 });
  doc.save("summary.pdf");
  console.log(">>> PDF נוצר ונשמר בשם summary.pdf");
});
