const isLocal = false;

const PRESIGN_ENDPOINT = isLocal
  ? "http://127.0.0.1:3000/presign"
  : "https://39m82loj48.execute-api.us-east-1.amazonaws.com/presign";

const SUMMARY_ENDPOINT = isLocal
  ? "http://127.0.0.1:3000/summary"
  : "https://39m82loj48.execute-api.us-east-1.amazonaws.com/summary";

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

async function fetchSummaryWithRetry(fileName, maxAttempts = 12, intervalMs = 10000) {
  let attempt = 0;
  while (attempt < maxAttempts) {
    attempt++;
    console.log(`>>> ניסיון ${attempt} לקבלת summary עבור ${fileName}`);
    try {
      const resp = await fetch(`${SUMMARY_ENDPOINT}?fileName=${encodeURIComponent(fileName)}`);
      console.log(">>> תשובת summary התקבלה. סטטוס:", resp.status);

      if (resp.status === 404) {
        updateStatus(`הסיכום עדיין בתהליך עיבוד... ניסיון ${attempt}/${maxAttempts}`, true);
        console.warn(">>> Summary not ready yet (404)");
        if (attempt < maxAttempts) {
          await new Promise(resolve => setTimeout(resolve, intervalMs));
          continue;
        } else {
          throw new Error("הסיכום לא נוצר גם אחרי המתנה של 2 דקות.");
        }
      }

      if (!resp.ok) {
        const errorBody = await resp.text();
        console.error(">>> גוף שגיאה מהשרת:", errorBody);
        throw new Error(`נכשל בקבלת סיכום: ${resp.status} ${errorBody}`);
      }

      const summaryData = await resp.json();
      console.log(">>> נתוני summary:", summaryData);
      renderSummary(summaryData);
      updateStatus("הסיכום התקבל בהצלחה!");
      return; // יציאה מוצלחת
    } catch (err) {
      console.error(">>> שגיאה בניסיון קבלת summary:", err);
      if (attempt >= maxAttempts) {
        updateStatus(`נכשל בקבלת סיכום אחרי ${maxAttempts} ניסיונות: ${err.message}`, true);
        return;
      } else {
        await new Promise(resolve => setTimeout(resolve, intervalMs));
      }
    }
  }
}

function renderSummary(summaryData) {
  let html = "";
  if (summaryData.sections) {
    summaryData.sections.forEach(section => {
      html += `<h3 style="margin-top:20px;">${section.title}</h3>`;
      html += "<ul>";
      section.bullets.forEach(bullet => {
        html += `<li>${bullet}</li>`;
      });
      html += "</ul>";
    });
  }

  // הצגת מטאדאטה למטה בקטן
  if (summaryData.raw) {
    html += `<div style="font-size:10px; color:gray; text-align:left; margin-top:20px;">${summaryData.raw}</div>`;
  }

  summaryText.innerHTML = html;
}

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) {
    updateStatus("אנא בחר קובץ שמע.", true);
    return;
  }

  try {
    const contentType = "application/octet-stream"; // אחידות מול backend
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

    // Polling for summary
    await fetchSummaryWithRetry(file.name);

  } catch (err) {
    console.error(">>> שגיאה כללית:", err);
    updateStatus(`העלאה נכשלה: ${err.message}`, true);
  }
});

// Download as PDF
// כאן תכניס את המחרוזת הארוכה מתוך assistant-base64.txt
const assistantFont = "<<<הכניסי כאן את המחרוזת Base64>>>";

downloadBtn.addEventListener('click', () => {
    console.log(">>> התחלת יצירת PDF להורדה");
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });

    // הוספת הפונט ל־VFS
    doc.addFileToVFS("Assistant.ttf", assistantFont);
    doc.addFont("Assistant.ttf", "Assistant", "normal");

    // שימוש בפונט Assistant
    doc.setFont("Assistant", "normal");
    doc.setFontSize(12);

    // יצירת טקסט מה־HTML
    const textContent = summaryText.innerText;
    doc.text(textContent, 40, 60, { maxWidth: 500 });

    doc.save("summary.pdf");
    console.log(">>> PDF נוצר ונשמר בשם summary.pdf");
});
