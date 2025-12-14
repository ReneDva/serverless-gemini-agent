const isLocal = false;

const PRESIGN_ENDPOINT = isLocal ? "http://127.0.0.1:3000/presign" : "https://rv41yjwq5c.execute-api.us-east-1.amazonaws.com/presign";

const SUMMARY_ENDPOINT = isLocal ? "http://127.0.0.1:3000/summary" : "https://rv41yjwq5c.execute-api.us-east-1.amazonaws.com/summary";

console.log(">>> PRESIGN_ENDPOINT:", PRESIGN_ENDPOINT);
console.log(">>> SUMMARY_ENDPOINT:", SUMMARY_ENDPOINT);

const fileInput = document.getElementById('file-upload');
const uploadBtn = document.getElementById('upload-btn');
const statusMessage = document.getElementById('status-message');
const summaryText = document.getElementById('summary-text');
const downloadBtn = document.getElementById('download-btn');
// --- עדכון הודעת סטטוס בטקסט ---
function updateStatus(message, isError = false) {
  const statusMessage = document.getElementById('status-message');
  if (statusMessage) {
    statusMessage.textContent = message;
    statusMessage.style.color = isError ? 'red' : 'green';
  }
  console.log(">>> עדכון סטטוס:", message, "שגיאה?", isError);
}

// --- עזרי DOM ---
function safeGet(id) {
  return document.getElementById(id);
}

// מיפוי של שלבי העיבוד להודעות ידידותיות
const stageFriendly = {
  "uploaded": "הקובץ התקבל במערכת",
  "split": "מכינים את הקובץ לחיתוך והעלאה",
  "transcribe_in_progress": "מתמללים את ההקלטה",
  "transcribe_completed": "התמלול הושלם",
  "merged": "ממזגים את התמלילים",
  "summarize_in_progress": "מכינים את הסיכום",
  "summarized": "הסיכום מוכן",
  // מצבי כשל
  "transcribe_failed": "אירעה שגיאה בתמלול",
  "summarize_failed": "אירעה שגיאה ביצירת הסיכום",
  "preprocess_failed": "אירעה שגיאה בעיבוד הקול",
  "convert_failed": "אירעה שגיאה בהמרת הקובץ"
};

// --- פונקציה שמחזירה הודעה ידידותית למשתמש ---
function friendlyProgressMessage(data, fileName) {
  console.debug(">>> Raw server response (data):", data);

  const name = data.original_name || fileName;
  const stage = data.stage || "in-progress";
  const friendlyStage = stageFriendly[stage] || "העיבוד בעיצומו";
  const completed = Number(data.completed_parts || 0);
  const total = data.total_parts ? Number(data.total_parts) : null;

  // טיפול במצבי כשל: אם stage הוא אחד מהכשלונות, נחזיר הודעה אדומה
  if (["transcribe_failed", "summarize_failed", "convert_failed", "preprocess_failed"].includes(stage)) {
    return `❌ "${name}" — ${friendlyStage}. אנא נסה שוב או בדוק את הקובץ.`;
  }

  let etaText = "";
  if (total && completed < total) {
    const remainingParts = total - completed;
    const estMin = Math.ceil((remainingParts * 20) / 60); // הערכה גסה בדקות
    etaText = ` (משוער: עוד כ־${estMin} דקות)`;
  }

  if (total) {
    return `העיבוד של "${name}" — ${friendlyStage}. הושלמו ${completed} מתוך ${total}${etaText}.`;
  } else {
    return `העיבוד של "${name}" — ${friendlyStage}.`;
  }
}


/// --- פונקציית polling ---
async function fetchSummaryWithRetry(fileName, internalId = null) {
  let attempt = 0;
  let maxAttempts = 15;
  let intervalMs = 20000;

  function buildQueryParam() {
    return internalId
      ? `id=${encodeURIComponent(internalId)}`
      : `fileName=${encodeURIComponent(fileName)}`;
  }

  while (attempt < maxAttempts) {
    attempt++;
    const queryParam = buildQueryParam();
    console.debug(`>>> fetchSummary attempt ${attempt}`, { fileName, internalId, queryParam });

    try {
      const url = `${SUMMARY_ENDPOINT}?${queryParam}`;
      const resp = await fetch(url);
      let data;
      try {
        data = await resp.json();
      } catch {
        const text = await resp.text().catch(() => '');
        console.debug(">>> Non‑JSON response text:", text);
        data = {};
      }

      // --- טיפול בתשובות ---
      if (resp.status === 200) {
        // סיכום מוכן
        if (typeof window.setProgress === 'function') {
          window.setProgress(30, 30, 30, true, 0); // כל השלבים מלאים, ETA=0
        }
        renderSummary(data);
        updateStatus(`הסיכום מוכן עבור "${data.original_name || fileName}".`, false);
        return;
      }

      if (resp.status === 202) {
        // סטטוס ביניים
        updateStatus(friendlyProgressMessage(data, fileName), false);

        let prePct = 0, transPct = 0, sumPct = 0;
        const stage = data.stage || '';
        const completed = Number(data.completed_parts || 0);
        const total = Number(data.total_parts || 0);

        // חישוב זמן משוער לפי חלקים
        let etaMinutes = null;
        if (total && completed < total) {
          const remainingParts = total - completed;
          etaMinutes = Math.ceil((remainingParts * 20) / 60); // 20 שניות לחלק
        }

        // העלאה – 10%
        if (stage === 'uploaded') {
          prePct = 10;
        }
        // עיבוד מקדים – עד 30%
        else if (stage === 'split') {
          prePct = 10 + (total ? Math.min(20, Math.round((completed / total) * 20)) : 20);
        }
        // תמלול ומיזוג – עוד 30%
        else if (stage.startsWith('transcribe') || stage === 'merged' || stage === 'transcribe_completed') {
          prePct = 30; // העלאה+עיבוד מקדים מלאים
          transPct = total ? Math.min(30, Math.round((completed / total) * 30)) : 30;
        }
        // סיכום – עוד 30%
        else if (stage.startsWith('summarize')) {
          prePct = 30; transPct = 30;
          sumPct = stage === 'summarized'
            ? 30
            : (total ? Math.min(30, Math.round((completed / total) * 30)) : 15);
        }

        if (typeof window.setProgress === 'function') {
          window.setProgress(prePct, transPct, sumPct, true, etaMinutes);
        }

        await new Promise(resolve => setTimeout(resolve, intervalMs));
        continue;
      }

      if (resp.status === 404) {
        updateStatus("הקובץ בתור לעיבוד. נעדכן בהמשך.", false);
        if (typeof window.setProgress === 'function') {
          window.setProgress(10, 0, 0, true, null); // רק העלאה, אין ETA
        }
        await new Promise(resolve => setTimeout(resolve, intervalMs));
        continue;
      }

      updateStatus(`שגיאה לא צפויה מהשרת: ${resp.status}`, true);
      return;

    } catch (err) {
      console.error(">>> Error fetching summary:", err);
      updateStatus(`שגיאת רשת: ${err.message}`, true);
      return;
    }
  }
  updateStatus("העיבוד לא הסתיים אחרי מספר ניסיונות.", true);
}

// --- upload-handler ---
(function attachUploadHandler() {
  function bind() {
    const fileInput = safeGet('file-upload');
    const uploadBtn = safeGet('upload-btn');

    if (!uploadBtn) return;
    if (uploadBtn.dataset.uploadHandlerAttached) return;
    uploadBtn.dataset.uploadHandlerAttached = '1';

    uploadBtn.addEventListener('click', async () => {
      const file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) {
        updateStatus("אנא בחר קובץ שמע.", true);
        return;
      }

      // בתחילת כל העלאה – גלגל ריק
      if (typeof window.setProgress === 'function') {
        window.setProgress(0, 0, 0, false, null);
      }

      try {
        const contentType = "application/octet-stream";
        console.debug(">>> Upload clicked. File info:", {
          name: file.name,
          size: file.size,
          type: file.type,
          PRESIGN_ENDPOINT
        });

        updateStatus(`1/2: מבקש כתובת presign עבור ${file.name}...`);

        // בקשת presign מהשרת
        const presignResp = await fetch(PRESIGN_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileName: file.name, contentType })
        });

        console.debug(">>> Presign response status:", presignResp.status);
        const presignData = await presignResp.json().catch(() => ({}));
        console.debug(">>> Presign response body:", presignData);

        const uploadUrl = presignData.uploadUrl;
        const fileKey = presignData.fileKey;

        if (!uploadUrl) throw new Error("presign response missing uploadUrl");

        updateStatus("2/2: מעלה קובץ ישירות ל‑S3...");
        console.debug(">>> PUT to S3:", { uploadUrl, contentType, fileKey });

        // העלאה ל-S3
        const putResp = await fetch(uploadUrl, {
          method: 'PUT',
          headers: { 'Content-Type': contentType },
          body: file
        });

        console.debug(">>> S3 PUT response status:", putResp.status);
        if (!putResp.ok) throw new Error(`העלאה ל‑S3 נכשלה: ${putResp.status}`);

        updateStatus("העלאה הצליחה! מתחיל עיבוד...");

        // אחרי העלאה מוצלחת – מציג את הגלגל עם 10% (שלב העלאה)
        if (typeof window.setProgress === 'function') {
          window.setProgress(10, 0, 0, true, null);
        }

        await fetchSummaryWithRetry(file.name, fileKey && fileKey !== file.name ? fileKey : null);

      } catch (err) {
        console.error(">>> Upload error:", err);
        updateStatus(`העלאה נכשלה: ${err.message}`, true);
      }
    });
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(bind, 0);
  } else {
    document.addEventListener('DOMContentLoaded', bind);
  }
})();


// =======================
// renderSummary / helpers
// =======================

function parseMetadata(rawText) {
  const metadata = {};
  if (!rawText || typeof rawText !== 'string') return metadata;
  const versionMatch = rawText.match(/model_version='([^']+)'/);
  if (versionMatch) metadata.model_version = versionMatch[1];

  const responseMatch = rawText.match(/response_id='([^']+)'/);
  if (responseMatch) metadata.response_id = responseMatch[1];

  const tokensMatch = rawText.match(/total_token_count=(\d+)/);
  if (tokensMatch) metadata.total_token_count = tokensMatch[1];

  return metadata;
}

function extractJsonFromRaw(rawText) {
  if (!rawText || typeof rawText !== 'string') return null;
  const match = rawText.match(/```json([\s\S]*?)```/);
  if (match) {
    try {
      return JSON.parse(match[1]);
    } catch (e) {
      console.error("Failed to parse JSON from raw:", e);
    }
  }
  return null;
}

function renderSummary(summaryData) {
  const summaryTextEl = safeGet("summary-text");
  const summaryContainer = safeGet("summary-container");
  if (!summaryTextEl || !summaryContainer) {
    console.warn("summary elements not found; cannot render summary");
    return;
  }

  let html = "";

  // אם יש sections ישירות
  if (summaryData && Array.isArray(summaryData.sections)) {
    summaryData.sections.forEach(section => {
      html += `<h3 style="margin-top:20px; font-weight:bold;">${escapeHtml(section.title)}</h3>`;
      html += "<ul>";
      (section.bullets || []).forEach(bullet => {
        html += `<li>${escapeHtml(bullet)}</li>`;
      });
      html += "</ul>";
    });
  }

  // אם יש raw – ננסה לחלץ ממנו JSON
  if (summaryData && summaryData.raw) {
    const parsed = extractJsonFromRaw(summaryData.raw);
    if (parsed && Array.isArray(parsed.sections)) {
      parsed.sections.forEach(section => {
        html += `<h3 style="margin-top:20px; font-weight:bold;">${escapeHtml(section.title)}</h3>`;
        html += "<ul>";
        (section.bullets || []).forEach(bullet => {
          html += `<li>${escapeHtml(bullet)}</li>`;
        });
        html += "</ul>";
      });
    }

    // מטא־דאטה
    const meta = parseMetadata(summaryData.raw);
    html += `<div style="font-size:10px; color:gray; text-align:right; margin-top:20px;">`;
    if (meta.model_version) html += `גרסת מודל: ${escapeHtml(meta.model_version)}<br>`;
    if (meta.response_id) html += `מזהה תשובה: ${escapeHtml(meta.response_id)}<br>`;
    if (meta.total_token_count) html += `מספר טוקנים: ${escapeHtml(meta.total_token_count)}<br>`;
    html += `</div>`;
  }

  summaryTextEl.innerHTML = html || "<div>לא נמצא תוכן להצגה.</div>";
  summaryContainer.style.display = "block";

  // שמירה גלובלית לשימוש ב‑PDF
  window.currentSummaryData = summaryData;
}

// פשוטה ובטוחה: מניעת XSS על טקסטים שמגיעים מהשרת
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// =======================
// PDF generation (jsPDF) - חיבור בטוח לכפתור הורדה
// =======================
(function attachDownloadHandler() {
  function bind() {
    const downloadBtn = safeGet('download-btn');
    const summaryTextEl = safeGet('summary-text');
    if (!downloadBtn) {
      console.warn('download-btn not found; PDF handler not attached');
      return;
    }
    if (downloadBtn.dataset.downloadHandlerAttached) {
      console.debug('download handler already attached; skipping');
      return;
    }
    downloadBtn.dataset.downloadHandlerAttached = '1';

    downloadBtn.addEventListener('click', () => {
      try {
        console.log(">>> Starting PDF generation");
        const { jsPDF } = window.jspdf || {};
        if (!jsPDF) {
          console.error("jsPDF not available");
          return;
        }
        const doc = new jsPDF({ orientation: 'p', unit: 'pt', format: 'a4' });

        // Load fonts if loader provided
        if (typeof loadFonts === 'function') {
          try { loadFonts(doc); } catch (e) { console.debug("loadFonts failed:", e); }
        }

        // Set default font (attempt; if not available, jsPDF falls back)
        try { doc.setFont("NotoSansHebrew", "regular"); } catch (e) { /* ignore */ }
        doc.setFontSize(12);

        let y = 40;
        const margin = 40;
        const maxWidth = 500;
        const xRight = margin + maxWidth;

        // Small header top-left (English only to avoid bidi issues)
        doc.setFontSize(10);
        doc.text("Generated by serverless-gemini-agent by Rene", margin, y, { align: "left" });
        y += 30;

        // Process summary sections from DOM safely
        if (summaryTextEl) {
          // querySelectorAll on the element
          const nodes = summaryTextEl.querySelectorAll("h3, ul");
          nodes.forEach(el => {
            if (el.tagName === "H3") {
              doc.setFontSize(14);
              try { doc.setFont("NotoSansHebrew", "bold"); } catch (e) {}
              const title = reverseHebrewLine(el.textContent.trim());
              doc.text(title, xRight, y, { align: "right" });
              try { doc.setFont("NotoSansHebrew", "regular"); } catch (e) {}
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
        }

        // Metadata block – use raw summaryData saved globally
        if (window.currentSummaryData && window.currentSummaryData.raw) {
          const meta = parseMetadata(window.currentSummaryData.raw);
          doc.setFontSize(10);
          doc.setTextColor(128, 128, 128); // אפור
          const spacing = 8;

          const drawMetaLine = (labelHebrew, value) => {
            const label = reverseHebrewLine(labelHebrew);
            const valueStr = String(value);
            const labelWidth = doc.getTextWidth(label);
            const valueX = xRight - labelWidth - spacing;
            doc.text(label, xRight, y, { align: "right" });
            doc.text(valueStr, valueX, y, { align: "right" });
            y += 12;
          };

          if (meta.model_version) drawMetaLine("גרסת מודל:", meta.model_version);
          if (meta.response_id) drawMetaLine("מזהה תשובה:", meta.response_id);
          if (meta.total_token_count) drawMetaLine("מספר טוקנים:", meta.total_token_count);

          doc.setTextColor(0, 0, 0);
        }

        doc.save("summary.pdf");
        console.log(">>> PDF generated and saved as summary.pdf");
      } catch (err) {
        console.error("PDF generation failed:", err);
      }
    });
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(bind, 0);
  } else {
    document.addEventListener('DOMContentLoaded', bind);
  }
})();
