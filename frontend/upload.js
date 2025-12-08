const isLocal = false;

const PRESIGN_ENDPOINT = isLocal ? "http://127.0.0.1:3000/presign" : "https://cbnok9mh96.execute-api.us-east-1.amazonaws.com/presign";

const SUMMARY_ENDPOINT = isLocal ? "http://127.0.0.1:3000/summary" : "https://cbnok9mh96.execute-api.us-east-1.amazonaws.com/summary";

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

async function fetchSummaryWithRetry(fileName, maxAttempts = 15, intervalMs = 20000) {
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

// Extract metadata from raw string
function parseMetadata(rawText) {
    const metadata = {};
    const versionMatch = rawText.match(/model_version='([^']+)'/);
    if (versionMatch) metadata.model_version = versionMatch[1];

    const responseMatch = rawText.match(/response_id='([^']+)'/);
    if (responseMatch) metadata.response_id = responseMatch[1];

    const tokensMatch = rawText.match(/total_token_count=(\d+)/);
    if (tokensMatch) metadata.total_token_count = tokensMatch[1];

    return metadata;
}

// Render summary content into the DOM
function renderSummary(summaryData) {
    let html = "";

    if (summaryData.sections) {
        summaryData.sections.forEach(section => {
            html += `<h3 style="margin-top:20px; font-weight:bold;">${section.title}</h3>`;
            html += "<ul>";
            section.bullets.forEach(bullet => {
                html += `<li>${bullet}</li>`;
            });
            html += "</ul>";
        });
    }

    // Metadata filtering and translation
    if (summaryData.raw) {
        const meta = parseMetadata(summaryData.raw);
        html += `<div style="font-size:10px; color:gray; text-align:right; margin-top:20px;">`;
        if (meta.model_version) html += `גרסת מודל: ${meta.model_version}<br>`;
        if (meta.response_id) html += `מזהה תשובה: ${meta.response_id}<br>`;
        if (meta.total_token_count) html += `מספר טוקנים: ${meta.total_token_count}<br>`;
        html += `</div>`;
    }

    summaryText.innerHTML = html;
    document.getElementById("summary-container").style.display = "block";

    // שמירה גלובלית לשימוש ב-PDF
    window.currentSummaryData = summaryData;
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

// Reverse Hebrew text for RTL rendering in jsPDF
function reverseHebrewLine(line) {
    return line.split('').reverse().join('');
}

downloadBtn.addEventListener('click', () => {
    console.log(">>> Starting PDF generation");
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });

    // Load all fonts from font-loader.js
    loadFonts(doc);
    console.log(doc.getFontList());

    // Set default font (NotoSansHebrew Regular)
    doc.setFont("NotoSansHebrew", "regular");
    doc.setFontSize(12);

    let y = 40;
    const margin = 40;
    const maxWidth = 500;
    const xRight = margin + maxWidth;

    // Small header top-left (English only to avoid bidi issues)
    doc.setFontSize(10);
    doc.text("Generated by serverless-gemini-agent by Rene", margin, y, { align: "left" });
    y += 30;

    // Process summary sections from DOM
    const sections = summaryText.querySelectorAll("h3, ul");
    sections.forEach(el => {
        if (el.tagName === "H3") {
            doc.setFontSize(14);
            doc.setFont("NotoSansHebrew", "bold"); // use bold variant
            const title = reverseHebrewLine(el.textContent.trim());
            doc.text(title, xRight, y, { align: "right" });
            doc.setFont("NotoSansHebrew", "regular");
            y += 24;
        } else if (el.tagName === "UL") {
            doc.setFontSize(12);
            el.querySelectorAll("li").forEach(li => {
                const text = reverseHebrewLine(li.textContent.trim());
                const bullet = text + " •";
                const lines = doc.splitTextToSize(bullet, maxWidth);
                lines.forEach(line => {
                    doc.text(line, xRight, y, { align: "right" });
                    y += 18;
                });
            });
            y += 10;
        }
    });

    // Metadata block – use raw summaryData saved globally
    if (window.currentSummaryData && window.currentSummaryData.raw) {
        const meta = parseMetadata(window.currentSummaryData.raw);

        doc.setFontSize(10);
        doc.setTextColor(128, 128, 128); // אפור

        const spacing = 8;

        const drawMetaLine = (labelHebrew, value) => {
            const label = reverseHebrewLine(labelHebrew); // הכותרת בעברית הפוכה
            const valueStr = String(value);

            const labelWidth = doc.getTextWidth(label);
            const valueX = xRight - labelWidth - spacing;

            // הצגת הכותרת בעברית בצד ימין
            doc.text(label, xRight, y, { align: "right" });

            // הצגת הערך משמאל לה
            doc.text(valueStr, valueX, y, { align: "right" });

            y += 12;
        };

        if (meta.model_version) {
            drawMetaLine("גרסת מודל:", meta.model_version);
        }
        if (meta.response_id) {
            drawMetaLine("מזהה תשובה:", meta.response_id);
        }
        if (meta.total_token_count) {
            drawMetaLine("מספר טוקנים:", meta.total_token_count);
        }

        doc.setTextColor(0, 0, 0); // החזרת צבע שחור לטקסט הבא
    }





    doc.save("summary.pdf");
    console.log(">>> PDF generated and saved as summary.pdf");
});
