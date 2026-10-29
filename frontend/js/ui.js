/**
 * UI Renderer and DOM Manipulation Module
 */

class UIManager {
  constructor() {
    // DOM Elements
    this.apiStatusBadge = document.getElementById("apiStatusBadge");
    this.fileListContainer = document.getElementById("fileListContainer");
    this.fileCountBadge = document.getElementById("fileCountBadge");
    this.startExtractionBtn = document.getElementById("startExtractionBtn");
    
    // Progress
    this.progressCard = document.getElementById("progressCard");
    this.progressBar = document.getElementById("progressBar");
    this.progressPercent = document.getElementById("progressPercent");
    this.progressStatusText = document.getElementById("progressStatusText");
    this.progressDetails = document.getElementById("progressDetails");
    
    // Stats
    this.statTotalQuestions = document.getElementById("statTotalQuestions");
    this.statFilesProcessed = document.getElementById("statFilesProcessed");
    this.statImageQuestions = document.getElementById("statImageQuestions");
    this.statCompleteStatus = document.getElementById("statCompleteStatus");
    
    // Search & Filters
    this.searchInput = document.getElementById("searchInput");
    this.imageFilterSelect = document.getElementById("imageFilterSelect");
    this.questionsStream = document.getElementById("questionsStream");
    this.emptyState = document.getElementById("emptyState");
    
    // Action Buttons

    this.exportCsvBtn = document.getElementById("exportCsvBtn");
    this.exportExcelBtn = document.getElementById("exportExcelBtn");
    this.exportPdfBtn = document.getElementById("exportPdfBtn");
    this.viewRawJsonBtn = document.getElementById("viewRawJsonBtn");
    
    // Modals
    this.apiKeyModal = document.getElementById("apiKeyModal");
    this.rawJsonModal = document.getElementById("rawJsonModal");
    this.fileExportModal = document.getElementById("fileExportModal");
    this.apiKeyInput = document.getElementById("apiKeyInput");
    this.rawJsonContent = document.getElementById("rawJsonContent");
    this.copyJsonBtn = document.getElementById("copyJsonBtn");
    
    // File Export Modal Elements
    this.modalFileTitle = document.getElementById("modalFileTitle");
    this.modalFileSummary = document.getElementById("modalFileSummary");
    this.modalProcessedFilesList = document.getElementById("modalProcessedFilesList");
    // Processed Files Section
    this.processedFilesCard = document.getElementById("processedFilesCard");
    this.processedFilesContainer = document.getElementById("processedFilesContainer");
    this.processedFilesCountBadge = document.getElementById("processedFilesCountBadge");

    // Pairwise Verification Card Elements
    this.pairwiseVerificationCard = document.getElementById("pairwiseVerificationCard");
    this.pairwiseVerificationList = document.getElementById("pairwiseVerificationList");
    this.pairwiseSummaryBadge = document.getElementById("pairwiseSummaryBadge");

    this.checkTokensBtn = document.getElementById("checkTokensBtn");

    // Token Modal
    this.tokenModal = document.getElementById("tokenModal");
    this.tokenLoadingSpinner = document.getElementById("tokenLoadingSpinner");
    this.tokenReportContent = document.getElementById("tokenReportContent");
    this.tokenModalTitle = document.getElementById("tokenModalTitle");

    // Quota Tracker Elements
    this.quotaPill = document.getElementById("quotaPill");
    this.quotaPercentLabel = document.getElementById("quotaPercentLabel");
    this.quotaMiniBar = document.getElementById("quotaMiniBar");
    this.quotaModal = document.getElementById("quotaModal");
    this.closeQuotaModalBtn = document.getElementById("closeQuotaModalBtn");
    this.closeQuotaModalFooterBtn = document.getElementById("closeQuotaModalFooterBtn");
    this.quotaCircle = document.getElementById("quotaCircle");
    this.quotaModalPercent = document.getElementById("quotaModalPercent");
    this.qStatTotalLimit = document.getElementById("qStatTotalLimit");
    this.qStatUsedRequests = document.getElementById("qStatUsedRequests");
    this.qStatRemainingRequests = document.getElementById("qStatRemainingRequests");
    this.qStatTokensToday = document.getElementById("qStatTokensToday");
    this.qStatKeysCount = document.getElementById("qStatKeysCount");
    this.qStatResetCountdown = document.getElementById("qStatResetCountdown");
    this.quotaBarRemainingLabel = document.getElementById("quotaBarRemainingLabel");
    this.quotaBarMaxLabel = document.getElementById("quotaBarMaxLabel");
    this.quotaModalBarFill = document.getElementById("quotaModalBarFill");
    this.quotaModelsGrid = document.getElementById("quotaModelsGrid");
    this.runQuotaTestBtn = document.getElementById("runQuotaTestBtn");
    this.quotaTestResultBox = document.getElementById("quotaTestResultBox");
    this.manageKeysFromQuotaBtn = document.getElementById("manageKeysFromQuotaBtn");

    // Live Logs Elements
    this.openLiveLogsBtn = document.getElementById("openLiveLogsBtn");
    this.progressViewLogsBtn = document.getElementById("progressViewLogsBtn");
    this.liveLogsModal = document.getElementById("liveLogsModal");
    this.closeLiveLogsModalBtn = document.getElementById("closeLiveLogsModalBtn");
    this.closeLiveLogsFooterBtn = document.getElementById("closeLiveLogsFooterBtn");
    this.terminalWindow = document.getElementById("terminalWindow");
    this.terminalContent = document.getElementById("terminalContent");
    this.terminalEmpty = document.getElementById("terminalEmpty");
    this.logsAutoRefreshCheck = document.getElementById("logsAutoRefreshCheck");
    this.logsAutoScrollCheck = document.getElementById("logsAutoScrollCheck");
    this.logsSearchInput = document.getElementById("logsSearchInput");
    this.clearLogsBtn = document.getElementById("clearLogsBtn");
    this.downloadLogsBtn = document.getElementById("downloadLogsBtn");
    this.logFileSizeIndicator = document.getElementById("logFileSizeIndicator");
    this.logCountAll = document.getElementById("logCountAll");
    this.logCountInfo = document.getElementById("logCountInfo");
    this.logCountWarn = document.getElementById("logCountWarn");
    this.logCountError = document.getElementById("logCountError");
    this.activeLogLevelFilter = "ALL";

    this.allQuestions = [];
    this.batchResults = [];
    this.selectedTargetFile = null;
  }

  setBackendStatus(isOnline, keyConfigured) {
    this.apiStatusBadge.className = "status-chip " + (isOnline ? "online" : "offline");
    if (!isOnline) {
      this.apiStatusBadge.querySelector(".status-label").textContent = "Backend Offline";
    } else if (keyConfigured) {
      this.apiStatusBadge.querySelector(".status-label").textContent = "API Ready";
    } else {
      this.apiStatusBadge.querySelector(".status-label").textContent = "Key Required";
    }
  }

  renderFileList(files, onRemove, onFileClick) {
    this.fileListContainer.innerHTML = "";
    this.fileCountBadge.textContent = `${files.length} file${files.length === 1 ? '' : 's'}`;

    files.forEach((file, index) => {
      const item = document.createElement("div");
      item.className = "file-item clickable";
      
      const sizeFormatted = file.size > 0 ? (file.size / (1024 * 1024)).toFixed(2) + " MB" : (file.fromJob ? "Extracted" : "PDF");
      item.innerHTML = `
        <div class="file-info" title="Click to view file options: ${file.name}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <span class="file-name">${file.name}</span>
          <span class="file-size">(${sizeFormatted})</span>
        </div>
        <div style="display: flex; align-items: center; gap: 0.35rem;">
          <button class="file-remove-btn" data-index="${index}" title="Remove file">&times;</button>
        </div>
      `;

      item.querySelector(".file-info").addEventListener("click", () => {
        if (onFileClick) onFileClick(file.name);
      });

      item.querySelector(".file-remove-btn").addEventListener("click", (e) => {
        e.stopPropagation();
        onRemove(index);
      });

      this.fileListContainer.appendChild(item);
    });
  }

  showProgress(show, text = "", percent = 0, details = "") {
    if (show) {
      this.progressCard.classList.remove("hidden");
      this.progressStatusText.textContent = text;
      this.progressPercent.textContent = `${Math.round(percent)}%`;
      this.progressBar.style.width = `${percent}%`;
      this.progressDetails.textContent = details;
    } else {
      this.progressCard.classList.add("hidden");
    }
  }

  updateStats(results, onDownload) {
    let totalQ = 0;
    let imageQ = 0;
    let completeQ = 0;
    this.allQuestions = [];
    this.batchResults = results;

    (results || []).forEach(res => {
      (res.questions || []).forEach(q => {
        totalQ++;
        if (q.has_question_image || q.image_url || q.has_solution_image || q.solution_image_url || Object.values(q.options || {}).some(opt => opt && (opt.has_image || opt.image_url))) {
          imageQ++;
        }
        if (q.status === "complete") {
          completeQ++;
        }
        this.allQuestions.push({
          ...q,
          file_name: res.file_name,
          chapter_number: q.chapter_number || res.chapter_number || "",
          chapter_name: q.chapter_name || res.chapter_name || "",
          subject: q.subject || res.subject || ""
        });
      });
    });

    // Questions are already ordered naturally per document by the backend; preserve file sequence

    this.statTotalQuestions.textContent = totalQ;
    this.statFilesProcessed.textContent = (results || []).length;
    this.statImageQuestions.textContent = imageQ;
    this.statCompleteStatus.textContent = completeQ;

    const hasData = totalQ > 0;

    this.exportCsvBtn.disabled = !hasData;
    this.exportExcelBtn.disabled = !hasData;
    if (this.exportPdfBtn) this.exportPdfBtn.disabled = !hasData;
    const exportImagesBtn = document.getElementById("exportImagesBtn");
    if (exportImagesBtn) exportImagesBtn.disabled = !(hasData && imageQ > 0);
    this.viewRawJsonBtn.disabled = !hasData;

    this.renderProcessedFilesCards(results, onDownload);
    this.renderQuestionsStream();
  }

  renderProcessedFilesCards(results, onDownload, pairwiseData = []) {
    if (!this.processedFilesCard || !this.processedFilesContainer) return;

    if (!results || results.length === 0) {
      this.processedFilesCard.classList.add("hidden");
      if (this.pairwiseVerificationCard) this.pairwiseVerificationCard.classList.add("hidden");
      return;
    }

    this.processedFilesCard.classList.remove("hidden");
    this.processedFilesCountBadge.textContent = `${results.length} PDF${results.length === 1 ? '' : 's'} Ready`;
    this.processedFilesContainer.innerHTML = "";

    // Render Pairwise Verification Summary
    if (this.pairwiseVerificationCard && this.pairwiseVerificationList) {
      const pairs = [];
      results.forEach(res => {
        if (res.matched_solution_filename || res.has_solution) {
          const totalQ = (res.questions || []).length;
          const verifiedQ = res.verified_solutions_count || totalQ;
          const rate = res.verification_rate !== undefined ? res.verification_rate : (totalQ > 0 ? Math.round((verifiedQ / totalQ) * 100) : 100);
          pairs.push({
            qFile: res.file_name,
            solFile: res.matched_solution_filename || "Solution PDF",
            totalQ: totalQ,
            verifiedQ: verifiedQ,
            unmatchedQ: res.unmatched_solutions_count || 0,
            rate: rate,
            isAdvance: res.is_advance
          });
        }
      });

      if (pairs.length > 0) {
        this.pairwiseVerificationCard.classList.remove("hidden");
        const all100 = pairs.every(p => p.rate >= 95);
        if (this.pairwiseSummaryBadge) {
          this.pairwiseSummaryBadge.textContent = all100 ? "✓ 100% Pairwise Verified" : `${pairs.length} Pair(s) Checked`;
          this.pairwiseSummaryBadge.style.background = all100 ? "#ecfdf5" : "#fef3c7";
          this.pairwiseSummaryBadge.style.color = all100 ? "#047857" : "#92400e";
          this.pairwiseSummaryBadge.style.borderColor = all100 ? "#a7f3d0" : "#fde68a";
        }

        this.pairwiseVerificationList.innerHTML = pairs.map(p => `
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem; padding: 0.75rem 1rem; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;">
            <div style="display: flex; align-items: center; gap: 0.65rem; font-size: 0.9rem;">
              <span style="font-weight: 700; color: #1e293b;">📄 ${this.escapeHtml(p.qFile)}</span>
              <span style="color: #64748b; font-weight: 800;">⟷</span>
              <span style="font-weight: 700; color: #047857; background: #ecfdf5; padding: 2px 8px; border-radius: 6px; border: 1px solid #a7f3d0;">💡 ${this.escapeHtml(p.solFile)}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.75rem; font-size: 0.85rem;">
              <span style="color: #475569;"><strong>${p.verifiedQ}</strong> / ${p.totalQ} Questions Verified</span>
              <span class="badge" style="background: ${p.rate >= 95 ? '#dcfce7' : '#fef3c7'}; color: ${p.rate >= 95 ? '#15803d' : '#b45309'}; border: 1px solid ${p.rate >= 95 ? '#86efac' : '#fde68a'}; font-weight: 800;">
                ${p.rate}% Match
              </span>
            </div>
          </div>
        `).join('');
      } else {
        this.pairwiseVerificationCard.classList.add("hidden");
      }
    }

    results.forEach(res => {
      const card = document.createElement("div");
      card.className = "processed-file-card";
      const isFailed = res.status === "failed";
      
      let resChNum = res.chapter_number;
      let resChName = res.chapter_name;
      if (!resChNum && res.file_name) {
        const m = res.file_name.match(/(?:chapter|chp|ch|unit|પ્રકરણ|અધ્યાય|ch\.)[\s\-_]*(\d+)/i) || res.file_name.match(/^(\d+)[\s\-_.:]/) || res.file_name.match(/^(\d+)\.pdf$/i);
        if (m) resChNum = m[1];
      }
      const fileChBadge = resChNum ? `<span class="badge" style="background: #fef3c7; color: #92400e; font-weight: 700; border: 1px solid #fde68a;">📖 Ch ${resChNum}${resChName && !resChName.toLowerCase().startsWith("chapter") ? `: ${this.escapeHtml(resChName)}` : ''}</span>` : '';

      const isAdvance = Boolean(res.is_advance);
      const examBadge = isAdvance
        ? `<span class="badge" style="background: #f3e8ff; color: #6b21a8; font-weight: 700; border: 1px solid #d8b4fe; margin-left: 6px;">⭐ JEE Advanced · 3 Excels</span>`
        : `<span class="badge" style="background: #eff6ff; color: #1e40af; font-weight: 600; border: 1px solid #bfdbfe; margin-left: 6px;">📘 JEE Main · 1 Excel</span>`;

      const topicBadge = (res.topics && res.topics.length > 0)
        ? `<span class="badge" style="background: #faf5ff; color: #6b21a8; font-weight: 700; border: 1px solid #d8b4fe; margin-left: 6px;">📚 ${res.topics.length} Topics</span>`
        : (res.has_textbook ? `<span class="badge" style="background: #faf5ff; color: #6b21a8; font-weight: 700; border: 1px solid #d8b4fe; margin-left: 6px;">📚 Textbook Linked</span>` : '');

      const solPairBadge = res.matched_solution_filename
        ? `<span class="badge" style="background: #ecfdf5; color: #047857; font-weight: 700; border: 1px solid #a7f3d0; margin-left: 6px;">💡 Paired: ${this.escapeHtml(res.matched_solution_filename)} (${res.verified_solutions_count || (res.questions || []).length}/${(res.questions || []).length} Verified · ${res.verification_rate !== undefined ? res.verification_rate : 100}%)</span>`
        : '';

      card.innerHTML = `
        <div class="pfc-left">
          <div class="pfc-icon">${isFailed ? "⚠️" : "📄"}</div>
          <div>
            <div class="pfc-name">${this.escapeHtml(res.file_name)} ${fileChBadge} ${examBadge} ${topicBadge} ${solPairBadge}</div>
            <div class="pfc-meta">
              ${isFailed 
                ? `<span style="color: #dc2626;">Error: ${this.escapeHtml(res.error_message || "Extraction failed")}</span>`
                : `<span>${(res.questions || []).length} questions</span> • <span>${res.total_pages_scanned || 1} pages</span> • <span>${res.processing_time_seconds || 0}s</span>${res.matched_solution_filename ? ` • <span style="color: #059669; font-weight: 600;">✓ Solutions Verified</span>` : ''}`
              }
            </div>
            ${isFailed && res.error_message ? `<div style="margin-top: 0.35rem; font-size: 0.8rem; color: #dc2626;">${this.escapeHtml(res.error_message)}</div>` : ''}
          </div>
        </div>
        <div class="pfc-actions">
          ${!isFailed ? `
          <button class="btn btn-excel btn-sm pfc-dl-excel" title="${isAdvance ? 'JEE Advanced Paper: Download 3 Separate Excel Files (Questions, Paragraph Type, Match the list)' : 'JEE Main Paper: Download Standard Excel (.xlsx)'}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M3 9h18M3 15h18"/></svg>
            <span>${isAdvance ? 'Download 3 Excel Files' : 'Download Excel'}</span>
          </button>
          <button class="btn btn-secondary btn-sm pfc-dl-csv" title="Download CSV file">
            <span>CSV</span>
          </button>
          <button class="btn btn-sm pfc-dl-pdf" title="Download Formatted PDF"
            style="background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;border:none;font-weight:600;">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            <span>PDF</span>
          </button>
          <button class="btn btn-primary btn-sm pfc-dl-json" title="Download Master JSON">
            <span>JSON</span>
          </button>
          ` : `
          <button class="btn btn-secondary btn-sm" onclick="document.getElementById('openApiKeyModalBtn').click()">
            <span>Update API Key</span>
          </button>
          `}
        </div>
      `;

      if (!isFailed) {
        card.querySelector(".pfc-dl-excel").addEventListener("click", () => {
          if (onDownload) onDownload("excel", res.file_name);
        });
        card.querySelector(".pfc-dl-csv").addEventListener("click", () => {
          if (onDownload) onDownload("csv", res.file_name);
        });
        card.querySelector(".pfc-dl-json").addEventListener("click", () => {
          if (onDownload) onDownload("json", res.file_name);
        });
        const pdfBtn = card.querySelector(".pfc-dl-pdf");
        if (pdfBtn) {
          pdfBtn.addEventListener("click", () => {
            if (onDownload) onDownload("pdf", res.file_name);
          });
        }
      }

      this.processedFilesContainer.appendChild(card);
    });
  }

  renderQuestionsStream() {
    const filterQuery = this.searchInput.value.toLowerCase().trim();
    const imageFilter = this.imageFilterSelect.value;

    const filtered = this.allQuestions.filter(q => {
      // Text and Chapter search
      const textMatch = !filterQuery || 
        (q.original_question && q.original_question.toLowerCase().includes(filterQuery)) ||
        (q.translated_question && q.translated_question.toLowerCase().includes(filterQuery)) ||
        (q.chapter_name && q.chapter_name.toLowerCase().includes(filterQuery)) ||
        (q.chapter_number && String(q.chapter_number).toLowerCase().includes(filterQuery)) ||
        (`ch ${q.chapter_number}`.toLowerCase().includes(filterQuery)) ||
        String(q.question_number || "").includes(filterQuery);

      // Image filter
      const hasImg = q.has_question_image || Boolean(q.image_url) || Boolean(q.has_solution_image) || Boolean(q.solution_image_url) || Object.values(q.options || {}).some(opt => opt && (opt.has_image || opt.image_url));
      const imgMatch = imageFilter === "all" || 
        (imageFilter === "with-image" && hasImg) ||
        (imageFilter === "text-only" && !hasImg);

      return textMatch && imgMatch;
    });

    if (filtered.length === 0) {
      this.questionsStream.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">🔍</div>
          <h3>${this.allQuestions.length === 0 ? "No Questions Extracted Yet" : "No Matching Questions"}</h3>
          <p>${this.allQuestions.length === 0 ? "Upload PDFs on the left panel to begin." : "Try adjusting your search query or filter criteria."}</p>
        </div>
      `;
      return;
    }

    this.questionsStream.innerHTML = "";
    filtered.forEach(q => {
      const card = this.createQuestionCard(q);
      this.questionsStream.appendChild(card);
    });

    // Trigger KaTeX auto-render on all newly added question cards
    if (typeof window.renderMathInPage === 'function') {
      window.renderMathInPage(this.questionsStream);
    }
  }

  _balanceBraces(str) {
    if (!str) return "";
    let openCount = 0;
    let closeCount = 0;
    for (let i = 0; i < str.length; i++) {
      if (str[i] === "{" && (i === 0 || str[i - 1] !== "\\")) openCount++;
      else if (str[i] === "}" && (i === 0 || str[i - 1] !== "\\")) closeCount++;
    }
    if (openCount > closeCount) {
      return str + "}".repeat(openCount - closeCount);
    }
    return str;
  }

  _splitMatrixRowElements(rowStr) {
    const tokens = [];
    let current = [];
    let pDepth = 0;
    let bDepth = 0;
    let i = 0;
    const s = String(rowStr).replace(/[\u2212\u2013\u2014\u2012\u2015]/g, '-').trim().replace(/^[|\[]+|[|\]]+$/g, '').trim();
    while (i < s.length) {
      const c = s[i];
      if (c === '(') pDepth++;
      else if (c === ')') pDepth = Math.max(0, pDepth - 1);
      else if (c === '{') bDepth++;
      else if (c === '}') bDepth = Math.max(0, bDepth - 1);
      else if (c === '&') {
        const tok = current.join('').trim();
        if (tok) tokens.push(tok);
        current = [];
        i++;
        continue;
      } else if ((c === ',' || c === ';') && pDepth === 0 && bDepth === 0) {
        const tok = current.join('').trim();
        if (tok) tokens.push(tok);
        current = [];
        i++;
        continue;
      } else if ((c === ' ' || c === '\t') && pDepth === 0 && bDepth === 0) {
        if (i + 1 < s.length && (s[i + 1] === ' ' || s[i + 1] === '\t')) {
          while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
          const tok = current.join('').trim();
          if (tok) tokens.push(tok);
          current = [];
          continue;
        }
      }
      current.push(c);
      i++;
    }
    const tok = current.join('').trim();
    if (tok) tokens.push(tok);
    return tokens;
  }

  _autoFormatMatrices(text) {
    if (!text) return "";

    // Normalize unicode minuses (e.g. \u2212 -> -)
    let res = String(text).replace(/[\u2212\u2013\u2014\u2012\u2015]/g, '-');

    // Helper to split matrix tokens respecting nested braces {} and parentheses ()
    const splitFlatTokens = (rawStr) => {
      const tokens = [];
      let current = [];
      let depth = 0;
      let pDepth = 0;
      for (let idx = 0; idx < rawStr.length; idx++) {
        const char = rawStr[idx];
        if (char === '{') {
          depth++;
          current.push(char);
        } else if (char === '}') {
          depth = Math.max(0, depth - 1);
          current.push(char);
        } else if (char === '(') {
          pDepth++;
          current.push(char);
        } else if (char === ')') {
          pDepth = Math.max(0, pDepth - 1);
          current.push(char);
        } else if ((char === ',' || char === ';' || char === ' ' || char === '\t' || char === '\n') && depth === 0 && pDepth === 0) {
          const tok = current.join('').trim();
          if (tok) tokens.push(tok);
          current = [];
        } else {
          current.push(char);
        }
      }
      const tok = current.join('').trim();
      if (tok) tokens.push(tok);
      return tokens;
    };

    // 1. Multi-line determinants: | sin(A+B+C) sin A cos A \n -sin A tan(A+B+C) tan A \n ... |
    res = res.replace(/\|\s*([^|]*?\n[^|]*?)\s*\|/g, (m, inner) => {
      const lines = inner.trim().split('\n').map(l => l.trim()).filter(Boolean);
      if (lines.length >= 2) {
        const rowStrs = lines.map(l => {
          const toks = this._splitMatrixRowElements(l);
          return toks.join(' & ');
        });
        return '\\begin{vmatrix} ' + rowStrs.join(' \\\\ ') + ' \\end{vmatrix}';
      }
      return m;
    });

    // 2. Multi-line bracketed rows: [ 1 0 -1 -2 \n 3 2 1 0 \n 5 4 3 2 ]
    res = res.replace(/\[\s*([0-9a-zA-Z\\+\-\.\s]*\n[0-9a-zA-Z\\+\-\.\s]*)\s*\]/g, (m, inner) => {
      const lines = inner.trim().split('\n').map(l => l.trim()).filter(Boolean);
      if (lines.length >= 2) {
        const rowStrs = lines.map(l => {
          const toks = this._splitMatrixRowElements(l);
          return toks.join(' & ');
        });
        return '\\begin{bmatrix} ' + rowStrs.join(' \\\\ ') + ' \\end{bmatrix}';
      }
      return m;
    });

    // 3. Single-line flattened matrix [ ... ] (4, 6, 8, 9, 12, 16, 20, 25 items)
    res = res.replace(/\[([^\[\]\n]{3,180})\]/g, (m, raw) => {
      // Avoid matching citations like [JEE Main 2020] or [Ans: A] or word tags
      if (/^(?:JEE|NEET|AIEEE|CBSE|Online|Ans|Shift|Hint|Page|Chapter|Image|Diagram)\b/i.test(raw.trim())) {
        return m;
      }

      let tokens = splitFlatTokens(raw.trim());

      // Unglue glued 2-digit OCR artifacts when total count is 3, 7, 8, 10, 11
      if (tokens.length === 3 && tokens.some(t => t.length >= 2 && !t.startsWith('-'))) {
        const exp = [];
        for (const t of tokens) {
          if (t.length === 2 && /^\d+$/.test(t)) {
            exp.push(t[0], t[1]);
          } else {
            exp.push(t);
          }
        }
        if (exp.length === 4) tokens = exp;
      } else if (tokens.length === 4 && tokens[3] === '12') {
        tokens[3] = '2';
      } else if (tokens.length === 7 || tokens.length === 8) {
        const exp = [];
        for (const t of tokens) {
          if (t.length === 2 && /^\d+$/.test(t)) {
            exp.push(t[0], t[1]);
          } else {
            exp.push(t);
          }
        }
        if (exp.length === 9) tokens = exp;
      } else if (tokens.length === 10 || tokens.length === 11) {
        const exp = [];
        for (const t of tokens) {
          if (/^-?\d{2}$/.test(t)) {
            exp.push(t.slice(0, -1), t.slice(-1));
          } else {
            exp.push(t);
          }
        }
        if (exp.length === 12) tokens = exp;
      }

      // Filter out plain non-math sentences in brackets
      const mathElemCount = tokens.filter(t => /^(?:[+-]?\d+(?:\.\d+)?|\\?[a-zA-Z][a-zA-Z0-9]*|\\frac\{[^{}]*\}\{[^{}]*\}|\\sqrt\{[^{}]*\}|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\pi|\\omega|\\sigma|\\Delta)$/.test(t)).length;
      if (tokens.length < 3 || (mathElemCount / tokens.length) < 0.6) {
        return m;
      }

      const n = tokens.length;
      if (n === 4) { // 2x2
        const r1 = tokens.slice(0, 2).join(' & ');
        const r2 = tokens.slice(2, 4).join(' & ');
        return `\\begin{bmatrix} ${r1} \\\\ ${r2} \\end{bmatrix}`;
      } else if (n === 9) { // 3x3
        const r1 = tokens.slice(0, 3).join(' & ');
        const r2 = tokens.slice(3, 6).join(' & ');
        const r3 = tokens.slice(6, 9).join(' & ');
        return `\\begin{bmatrix} ${r1} \\\\ ${r2} \\\\ ${r3} \\end{bmatrix}`;
      } else if (n === 12) { // 3x4 (3 rows of 4 columns)
        const r1 = tokens.slice(0, 4).join(' & ');
        const r2 = tokens.slice(4, 8).join(' & ');
        const r3 = tokens.slice(8, 12).join(' & ');
        return `\\begin{bmatrix} ${r1} \\\\ ${r2} \\\\ ${r3} \\end{bmatrix}`;
      } else if (n === 6) { // 2x3
        const r1 = tokens.slice(0, 3).join(' & ');
        const r2 = tokens.slice(3, 6).join(' & ');
        return `\\begin{bmatrix} ${r1} \\\\ ${r2} \\end{bmatrix}`;
      } else if (n === 8) { // 2x4
        const r1 = tokens.slice(0, 4).join(' & ');
        const r2 = tokens.slice(4, 8).join(' & ');
        return `\\begin{bmatrix} ${r1} \\\\ ${r2} \\end{bmatrix}`;
      } else if (n === 16) { // 4x4
        const r1 = tokens.slice(0, 4).join(' & ');
        const r2 = tokens.slice(4, 8).join(' & ');
        const r3 = tokens.slice(8, 12).join(' & ');
        const r4 = tokens.slice(12, 16).join(' & ');
        return `\\begin{bmatrix} ${r1} \\\\ ${r2} \\\\ ${r3} \\\\ ${r4} \\end{bmatrix}`;
      }
      return m;
    });

    // 4. Single-line flattened determinants | ... | (4, 9, 16 items)
    res = res.replace(/\|([^|\n]{3,180})\|/g, (m, raw) => {
      let tokens = splitFlatTokens(raw.trim());
      const mathElemCount = tokens.filter(t => /^(?:[+-]?\d+(?:\.\d+)?|\\?[a-zA-Z][a-zA-Z0-9]*|\\frac\{[^{}]*\}\{[^{}]*\}|\\sqrt\{[^{}]*\}|\\alpha|\\beta|\\gamma|\\delta|\\theta|\\lambda|\\mu|\\pi|\\omega|\\sigma|\\Delta)$/.test(t)).length;
      if (tokens.length < 4 || (mathElemCount / tokens.length) < 0.6) {
        return m;
      }
      const n = tokens.length;
      if (n === 4) { // 2x2
        const r1 = tokens.slice(0, 2).join(' & ');
        const r2 = tokens.slice(2, 4).join(' & ');
        return `\\begin{vmatrix} ${r1} \\\\ ${r2} \\end{vmatrix}`;
      } else if (n === 9) { // 3x3
        const r1 = tokens.slice(0, 3).join(' & ');
        const r2 = tokens.slice(3, 6).join(' & ');
        const r3 = tokens.slice(6, 9).join(' & ');
        return `\\begin{vmatrix} ${r1} \\\\ ${r2} \\\\ ${r3} \\end{vmatrix}`;
      } else if (n === 16) { // 4x4
        const r1 = tokens.slice(0, 4).join(' & ');
        const r2 = tokens.slice(4, 8).join(' & ');
        const r3 = tokens.slice(8, 12).join(' & ');
        const r4 = tokens.slice(12, 16).join(' & ');
        return `\\begin{vmatrix} ${r1} \\\\ ${r2} \\\\ ${r3} \\\\ ${r4} \\end{vmatrix}`;
      }
      return m;
    });

    // Format adjugate operators e.g. |A||adjA| or |adj A|
    res = res.replace(/\|A\|\|\s*adj\s*A\|/gi, '$|A|\\,|\\text{adj } A|$');
    res = res.replace(/(?<!\$)\|\s*adj\s*\(?([A-Za-z])\)?\s*\|(?!\$)/gi, '$|\\text{adj } $1|$');
    return res;
  }

  formatMathAndText(text) {
    if (!text) return "";
    if (typeof katex === "undefined") {
      return this.escapeHtml(text).replace(/\n/g, '<br>');
    }

    try {
      // FIX 0: Auto-format flattened or multi-line matrix brackets into standard LaTeX \begin{bmatrix} ... \end{bmatrix}
      let fixed = this._autoFormatMatrices(text);

      // FIX 1: Normalize double backslashes (e.g. \\frac -> \frac, \\Omega -> \Omega)
      fixed = fixed.replace(/\\\\([a-zA-Z{}\[\]().,])/g, '\\$1');

      // FIX 2: Fix glued Greek macros like \DeltaR → \Delta R
      fixed = fixed.replace(
        /\\(Alpha|Beta|Gamma|Delta|Epsilon|Zeta|Eta|Theta|Iota|Kappa|Lambda|Mu|Nu|Xi|Pi|Rho|Sigma|Tau|Upsilon|Phi|Chi|Psi|Omega|alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)([A-Z0-9])/g,
        '\\$1 $2'
      );

      // FIX 3: Normalize limits (\lim\limits_{x \to 0}) and sums (\sum\limits) so conditions display directly underneath
      fixed = this._normalizeLimits(fixed);

      // FIX 4: Pre-wrap bare LaTeX commands (e.g. \frac{a}{b}, \sqrt{x}, \alpha, \begin{bmatrix}) outside $ delimiters
      fixed = this._wrapBareLatex(fixed);

      // Process line-by-line for best typography
      const lines = fixed.split('\n');
      return lines.map(line => {
        if (!line.trim()) return '';
        return this._mathLine(line);
      }).join('<br>');

    } catch (err) {
      console.warn("KaTeX rendering warning:", err);
      return this.escapeHtml(text).replace(/\n/g, '<br>');
    }
  }

  _normalizeLimits(str) {
    if (!str) return "";
    // Normalize \lim_{...} -> \lim\limits_{...}
    let res = str.replace(/\\lim\s*(?!\\limits)\s*_\s*\{/g, '\\lim\\limits_{');
    res = res.replace(/\\lim\s*(?!\\limits)\s*_\s*([a-zA-Z0-9\\]+)/g, '\\lim\\limits_{$1}');
    // Normalize ASCII arrows -> or \rightarrow to \to inside limits (supporting nested braces)
    const limPrefix = '\\lim\\limits_{';
    let out = [];
    let i = 0;
    while (i < res.length) {
      if (res.startsWith(limPrefix, i)) {
        let start = i;
        i += limPrefix.length;
        let depth = 1;
        while (i < res.length && depth > 0) {
          if (res[i] === '{' && (i === 0 || res[i - 1] !== '\\')) depth++;
          else if (res[i] === '}' && (i === 0 || res[i - 1] !== '\\')) depth--;
          i++;
        }
        let limBlock = res.slice(start, i);
        limBlock = limBlock.replace(/\s*(?:->|-->|\\rightarrow)\s*/g, ' \\to ');
        out.push(limBlock);
      } else {
        out.push(res[i]);
        i++;
      }
    }
    res = out.join('');
    // Normalize sums and products to use \limits
    res = res.replace(/\\sum\s*(?!\\limits)\s*_\s*\{/g, '\\sum\\limits_{');
    res = res.replace(/\\prod\s*(?!\\limits)\s*_\s*\{/g, '\\prod\\limits_{');
    res = res.replace(/\\(max|min|sup|inf|colim)\s*(?!\\limits)\s*_\s*\{/g, '\\$1\\limits_{');

    // Inside math expressions, ensure fill-in-the-blank lines use clean solid underline or text
    res = res.replace(/\\text\{\s*\\(?:rule|underline)\s*\{[^}]*\}\s*(?:\{[^}]*\})?\s*\}/g, '\\underline{\\quad\\quad\\quad}');
    res = res.replace(/\\underline\{\s*(?:\\hspace\{[^}]*\}|\\quad|\\qquad|\\phantom\{[^}]*\}|\s*)*\}/g, '\\underline{\\quad\\quad\\quad}');
    res = res.replace(/\\text\{\s*(?:\\?_)+\s*\}/g, '\\underline{\\quad\\quad\\quad}');
    res = res.replace(/\\rule\{[^{}]*\}\{[^{}]*\}/g, '\\underline{\\quad\\quad\\quad}');

    return res;
  }

  _wrapBareLatex(text) {
    if (!text) return "";
    // Wrap entire \begin{env} ... \end{env} blocks if not already in $
    let res = text.replace(/(?<!\$)\\begin\{([a-zA-Z0-9\*]+)\}[\s\S]*?\\end\{\1\}(?!\$)/g, (m) => {
      return `$${m}$`;
    });

    // If text already has $ delimiters, split and wrap only non-delimited portions
    const parts = [];
    let lastIdx = 0;
    const re = /\$\$([\s\S]+?)\$\$|\$([^\$\n]+?)\$/g;
    let m;
    const macroPat = /(\\[a-zA-Z]+(?:\{[^{}]*\}|\[[^\[\]]*\]|[_^](?:\{[^{}]*\}|[0-9a-zA-Z]+))*(?:\s*[\+\-\*\/=\<\>]\s*(?:\\[a-zA-Z]+(?:\{[^{}]*\}|\[[^\[\]]*\]|[_^](?:\{[^{}]*\}|[0-9a-zA-Z]+))*|[0-9]+(?:\.[0-9]+)?|[a-zA-Z](?:[_^](?:\{[^{}]*\}|[0-9a-zA-Z]+))*))*)/g;

    while ((m = re.exec(res)) !== null) {
      if (m.index > lastIdx) {
        const seg = res.slice(lastIdx, m.index);
        parts.push(seg.replace(macroPat, '$$$1$'));
      }
      parts.push(m[0]);
      lastIdx = re.lastIndex;
    }
    if (lastIdx < res.length) {
      const seg = res.slice(lastIdx);
      parts.push(seg.replace(macroPat, '$$$1$'));
    }

    let combined = parts.join('');
    // Merge adjacent $...$$...$ into a single $...$
    combined = combined.replace(/\$([^\$\n]+)\$\s*\$([^\$\n]+)\$/g, '$$$1 $2$');
    return combined;
  }

  // Render one line: routes to delimited or bare-math renderer
  _mathLine(line) {
    // Already has $...$ or $$...$$ → use delimiter renderer
    if (line.includes('$')) {
      return this._renderDelimited(line);
    }
    // No LaTeX backslash commands → plain text
    if (!/\\[a-zA-Z]/.test(line)) {
      return this.escapeHtml(line);
    }
    // Has bare LaTeX (no $ delimiters yet) — render using math spans
    return this._mathSpans(line);
  }

  // Render text that already has $...$ / $$...$$ delimiters
  _renderDelimited(text) {
    let result = "";
    let lastIdx = 0;
    const re = /\$\$([\s\S]+?)\$\$|\$([^\$\n]+?)\$/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > lastIdx) {
        const seg = text.slice(lastIdx, m.index);
        result += /\\[a-zA-Z]/.test(seg) ? this._mathSpans(seg) : this.escapeHtml(seg);
      }
      const block = Boolean(m[1]);
      let expr = (m[1] || m[2] || '').trim();
      expr = expr.replace(/(?:\\?_){2,}/g, '\\underline{\\quad\\quad\\quad}');
      expr = this._normalizeLimits(this._balanceBraces(expr));
      if (expr) {
        try {
          result += katex.renderToString(expr, { displayMode: block, throwOnError: false, strict: false, trust: false });
        } catch (e) {
          result += `<span class="katex-math">${this.escapeHtml(expr)}</span>`;
        }
      }
      lastIdx = re.lastIndex;
    }
    if (lastIdx < text.length) {
      const seg = text.slice(lastIdx);
      result += /\\[a-zA-Z]/.test(seg) ? this._mathSpans(seg) : this.escapeHtml(seg);
    }
    return result;
  }

  // Scan text char-by-char, detect \command spans and render with KaTeX
  _mathSpans(text) {
    let result = "";
    let i = 0;
    while (i < text.length) {
      // 1. Handle complete \begin{env} ... \end{env} environments (bmatrix, pmatrix, vmatrix, cases, matrix, etc.)
      if (text.startsWith('\\begin{', i)) {
        const envM = text.slice(i).match(/^\\begin\{([a-zA-Z0-9\*]+)\}/);
        if (envM) {
          const envName = envM[1];
          const endTag = `\\end{${envName}}`;
          const endIdx = text.indexOf(endTag, i + envM[0].length);
          if (endIdx !== -1) {
            const expr = text.slice(i, endIdx + endTag.length);
            try {
              result += katex.renderToString(expr, { displayMode: false, throwOnError: false, strict: false, trust: false });
            } catch (e) {
              result += `<span class="katex-math">${this.escapeHtml(expr)}</span>`;
            }
            i = endIdx + endTag.length;
            continue;
          }
        }
      }

      if (text[i] === '\\' && i + 1 < text.length && /[a-zA-Z]/.test(text[i + 1])) {
        // Start of a LaTeX command — collect the full expression
        let j = i;
        let depth = 0;
        while (j < text.length) {
          const c = text[j];
          if (c === '{') { depth++; j++; continue; }
          if (c === '}') {
            if (depth > 0) { depth--; j++; continue; }
            break; // Unmatched close brace
          }
          if (depth > 0) { j++; continue; } // Inside braces: consume everything
          // depth === 0:
          if (c === '\\' && j + 1 < text.length && /[a-zA-Z]/.test(text[j + 1])) {
            j++; // Skip backslash
            while (j < text.length && /[a-zA-Z]/.test(text[j])) j++;
            continue;
          }
          if (c === '_' && ((j + 1 < text.length && text[j + 1] === '_') || (j > i && text[j - 1] === '_'))) {
            // Consecutive underscores (fill-in-the-blank), not a subscript! Stop math span here.
            break;
          }
          if (/[0-9A-Za-z.+\-*=^_()|[\]']/.test(c)) { j++; continue; }
          if (c === ' ') {
            // Continue through space if math-like token follows, but stop before blank underline
            let k = j + 1;
            while (k < text.length && text[k] === ' ') k++;
            if (k < text.length && text[k] === '_' && k + 1 < text.length && text[k + 1] === '_') {
              break; // Blank line follows, end math span
            }
            if (k < text.length && /[\\0-9A-Za-z{=+\-*^_(]/.test(text[k])) { j++; continue; }
            break;
          }
          break;
        }
        let expr = text.slice(i, j).trim();
        expr = expr.replace(/(?:\\?_){2,}/g, '\\underline{\\quad\\quad\\quad}');
        expr = this._normalizeLimits(this._balanceBraces(expr));
        if (expr) {
          try {
            result += katex.renderToString(expr, { displayMode: false, throwOnError: false, strict: false, trust: false });
          } catch (e) {
            result += `<span class="katex-math">${this.escapeHtml(expr)}</span>`;
          }
        }
        i = j;
      } else {
        result += this.escapeHtml(text[i]);
        i++;
      }
    }
    return result;
  }

  cleanQuestionText(text) {
    if (!text) return "";
    let cleaned = text.trim();
    
    const citationPatterns = [
      /\s*[\(\[]\s*(?:Online|JEE(?:\s+Main|\s+Adv|\s+Advanced)?|NEET|AIEEE|GUJCET|CBSE|AIIMS|AIPMT|ISEET|BITSAT|IIT)\b[^\)\]]*?(?:19\d\d|20\d\d|Jan|Feb|March|April|May|June|July|Aug|Sep|Oct|Nov|Dec)[^\)\]]*[\)\]]\s*$/gi,
      /^\s*[\(\[]\s*(?:Online|JEE(?:\s+Main|\s+Adv|\s+Advanced)?|NEET|AIEEE|GUJCET|CBSE|AIIMS|AIPMT|ISEET|BITSAT|IIT)\b[^\)\]]*?(?:19\d\d|20\d\d|Jan|Feb|March|April|May|June|July|Aug|Sep|Oct|Nov|Dec)[^\)\]]*[\)\]]\s*/gi,
      /\s*[\(\[]\s*(?:(?:19|20)\d\d\s*,\s*)?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))[^\)\]]*?(?:19\d\d|20\d\d|Shift|I{1,3}|IV|V)[^\)\]]*[\)\]]\s*$/gi,
      /\s*[\(\[]\s*(?:19|20)\d\d\s+(?:Main|Adv|Online|NEET|Shift|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[^\)\]]*[\)\]]\s*$/gi
    ];

    let changed = true;
    while (changed) {
      const prev = cleaned;
      citationPatterns.forEach(pat => {
        cleaned = cleaned.replace(pat, "").trim();
      });
      changed = (cleaned !== prev);
    }

    // If not a matching question, strip trailing options block from question stem to avoid duplication
    if (!/column|list|match/i.test(cleaned)) {
      const optMatch = cleaned.match(/(?:^|[\r\n]+|\s+)(?:[\(\[]\s*[aA1અक]\s*[\)\]]|[aA1અक][\.\:\)])\s+[\s\S]+?(?:[\(\[]\s*[bB2બख]\s*[\)\]]|[bB2બख][\.\:\)])\s+[\s\S]+/i);
      if (optMatch && optMatch.index > 5) {
        cleaned = cleaned.slice(0, optMatch.index).trim();
      }
    }

    return cleaned;
  }

  createQuestionCard(q) {
    const card = document.createElement("div");
    card.className = "mcq-card";

    // Option details recovery: check if options are inside opts or embedded in question text
    let opts = q.options || {};
    const optLetters = ["A", "B", "C", "D"];
    const rawAns = (q.answer || "").trim();
    const qType = q.question_type || "MCQ";
    const isExplicitNumeric = /numeric|integer|nat/i.test(qType);

    // If options are missing or incomplete in opts object, extract from question text
    let hasValidOptions = optLetters.some(letter => {
      const opt = opts[letter];
      return opt && (opt.original || opt.translated || opt.image_url || opt.has_image);
    });

    const fullQuestionText = (q.translated_question || q.original_question || "").trim();
    if (!hasValidOptions && !isExplicitNumeric) {
      const optMatch = fullQuestionText.match(/(?:^|[\r\n]+|\s+)(?:[\(\[]\s*([aA1અक])\s*[\)\]]|[aA1અक][\.\:\)])\s+([\s\S]+?)(?:[\(\[]\s*([bB2બख])\s*[\)\]]|[bB2બख][\.\:\)])\s+([\s\S]+?)(?:[\(\[]\s*([cC3કग])\s*[\)\]]|[cC3કग][\.\:\)])\s+([\s\S]+?)(?:[\(\[]\s*([dD4ડघ])\s*[\)\]]|[dD4ડघ][\.\:\)])\s+([\s\S]+?)$/i);
      if (optMatch) {
        opts = {
          "A": { translated: optMatch[2].trim(), original: optMatch[2].trim() },
          "B": { translated: optMatch[4].trim(), original: optMatch[4].trim() },
          "C": { translated: optMatch[6].trim(), original: optMatch[6].trim() },
          "D": { translated: optMatch[8].trim(), original: optMatch[8].trim() },
        };
        hasValidOptions = true;
      }
    }

    // Strict MCQ Answer Parsing: map 1->A, 2->B, 3->C, 4->D, and letters A-D
    let cleanMcqAns = "";
    let displayAns = "";

    if (rawAns) {
      const numToLetter = { '1': 'A', '2': 'B', '3': 'C', '4': 'D', 'અ': 'A', 'બ': 'B', 'ક': 'C', 'ડ': 'D', 'क': 'A', 'ख': 'B', 'ग': 'C', 'घ': 'D' };
      const singleLetterM = rawAns.match(/^(?:ans(?:wer)?|key|option|વિકલ્પ)?[\s:\.\=\-]*[\(\[]?\s*([A-Da-d1-4અબકડक-घ])\s*[\)\]]?$/i);

      if (singleLetterM) {
        const rawK = singleLetterM[1].toUpperCase();
        cleanMcqAns = numToLetter[rawK] || (['A', 'B', 'C', 'D'].includes(rawK) ? rawK : '');
      } else if (/^[A-D](\s*,\s*[A-D])*$/i.test(rawAns)) {
        const letters = rawAns.toUpperCase().split(/[,\s]+/).filter(Boolean);
        cleanMcqAns = (qType === "Multiple" || /multiple/i.test(qType)) ? letters.join(', ') : letters[0];
      }

      // If this is an MCQ and we found an option letter, do NOT treat it as numeric!
      if (!cleanMcqAns && (isExplicitNumeric || !hasValidOptions)) {
        let s = rawAns.replace(/^(?:ans(?:wer)?|જવાબ|ઉત્તર|key)\s*(?:is|:|:=|-|\.|\/|=)?\s*/i, '').replace(/^[=:]\s*/, '').trim();
        let m_wrap = s.match(/^[\(\[\{]\s*([+-]?\d+(?:\.\d+)?|[+-]?\d+\s*\/\s*\d+)\s*[\)\]\}]$/);
        if (m_wrap) {
          displayAns = m_wrap[1].replace(/\s+/g, '');
        } else {
          let numM = s.match(/[+-]?\d+(?:\.\d+)?(?:\s*\/\s*\d+)?/);
          displayAns = numM ? numM[0].replace(/\s+/g, '') : s;
        }
      }
    }

    const isNumeric = isExplicitNumeric || (!hasValidOptions && Boolean(displayAns) && !cleanMcqAns);

    let optionsHtml = '';
    if (hasValidOptions && !isExplicitNumeric) {
      optionsHtml = '<div class="options-grid">';
      const correctList = cleanMcqAns ? cleanMcqAns.split(",").map(s => s.trim()) : [];
      optLetters.forEach(letter => {
        const opt = opts[letter];
        const optText = opt ? (opt.original || opt.translated || "") : "";
        const hasImg = opt && (opt.has_image || opt.image_url);
        const isCorrect = correctList.includes(letter);

        // Determine the image URL to show: prefer opt.image_url,
        // fallback to answer_image_url if this option is the correct answer
        const optImgUrl = (opt && opt.image_url)
          ? opt.image_url
          : (isCorrect && q.answer_image_url ? q.answer_image_url : null);

        if (!optText && !hasImg && !isCorrect) return;

        optionsHtml += `
          <div class="option-box ${isCorrect ? 'is-correct' : ''}">
            <div class="option-letter ${isCorrect ? 'is-correct-letter' : ''}">${letter}</div>
              <div class="option-content">
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;">
                ${optText ? `<div class="option-orig">${this.formatMathAndText(optText)}</div>` : '<div></div>'}
                ${isCorrect ? `<span class="correct-tag">✓ Correct Option</span>` : ''}
              </div>
              ${optImgUrl ? `
                <div style="margin-top: 0.5rem; display: flex; align-items: center; justify-content: center;">
                  <img src="${this.escapeHtml(optImgUrl)}" alt="Option ${letter}" style="max-height: 200px; max-width: 100%; border-radius: 6px; object-fit: contain; background: #ffffff;" />
                </div>
              ` : ''}
            </div>
          </div>
        `;
      });
      optionsHtml += '</div>';
    }

    // Matching Column rendering (Column A / Column-I and Column B / Column-II)
    let colI = (q.column_i || q.column_a || q.list_i || q.list_a || "").trim();
    let colII = (q.column_ii || q.column_b || q.list_ii || q.list_b || "").trim();
    const isMatching = qType.toLowerCase().includes("match") || Boolean(colI || colII);

    if (isMatching && (!colI || !colII)) {
      const fullText = (q.translated_question || q.original_question || "");
      const col1M = fullText.match(/(?:column[\s\-_]*(?:i\b|1\b|a\b)|list[\s\-_]*(?:i\b|1\b|a\b)|કૉલમ[\s\-_]*(?:i|૧|1|a))/i);
      const col2M = fullText.match(/(?:column[\s\-_]*(?:ii\b|2\b|b\b)|list[\s\-_]*(?:ii\b|2\b|b\b)|કૉલમ[\s\-_]*(?:ii|૨|2|b))/i);
      if (col1M && col2M && col1M.index < col2M.index) {
        if (!colI) colI = fullText.substring(col1M.index + col1M[0].length, col2M.index).trim();
        if (!colII) {
          const afterCol2 = fullText.substring(col2M.index + col2M[0].length);
          const endOpts = afterCol2.match(/(?:\n\s*(?:options?|codes?|વિકલ્પો)\s*[:\.\-]?|\n\s*\([a-dA-D]\)\s+)/i);
          colII = endOpts ? afterCol2.substring(0, endOpts.index).trim() : afterCol2.trim();
        }
      }
    }

    let matchingColumnsHtml = '';
    if (colI || colII) {
      const colImgs = [
        { label: "A", url: q.column_i_a_image_url },
        { label: "B", url: q.column_i_b_image_url },
        { label: "C", url: q.column_i_c_image_url },
        { label: "D", url: q.column_i_d_image_url },
      ].filter(item => Boolean(item.url));

      matchingColumnsHtml = `
        <div class="matching-columns-container">
          <div class="matching-column-box">
            <div class="matching-column-title">
              <span>📋 Column A / Column-I</span>
            </div>
            <div class="matching-column-content">${this.formatMathAndText(colI || "—")}</div>
            ${colImgs.length > 0 ? `
              <div class="matching-col-images" style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.5rem;">
                ${colImgs.map(ci => `
                  <div style="border: 1px solid #e2e8f0; border-radius: 6px; padding: 4px; background: #fff; text-align: center;">
                    <div style="font-size: 0.7rem; font-weight: 700; color: #475569;">(${ci.label})</div>
                    <img src="${this.escapeHtml(ci.url)}" style="max-height: 120px; max-width: 100%; object-fit: contain;" />
                  </div>
                `).join('')}
              </div>
            ` : ''}
          </div>
          <div class="matching-column-box">
            <div class="matching-column-title">
              <span>📋 Column B / Column-II</span>
            </div>
            <div class="matching-column-content">${this.formatMathAndText(colII || "—")}</div>
          </div>
        </div>
      `;
    }

    let numericAnswerHtml = '';
    if (isNumeric) {
      numericAnswerHtml = `
        <div class="numeric-answer-box" style="margin: 0.8rem 0; padding: 0.75rem 1rem; background: #fffbeb; border: 1.5px solid #fde68a; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; gap: 1rem;">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span style="font-size: 1.35rem;">🔢</span>
            <div>
              <div style="font-size: 0.75rem; color: #92400e; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">Numerical Answer / Value</div>
              <div style="font-size: 1.2rem; font-weight: 800; color: #78350f; font-family: monospace;">${this.escapeHtml(displayAns || "Not specified")}</div>
            </div>
          </div>
          ${displayAns ? `<span class="correct-tag" style="background: #fef08a; color: #854d0e; border-color: #facc15;">✓ Calculated Value</span>` : ''}
        </div>
      `;
    }

    const rawSol = (q.solution || "").trim();
    const hasValidSol = Boolean((rawSol && !['null', 'none', 'undefined', '-', '--', 'na', 'n/a', '?'].includes(rawSol.toLowerCase())) || q.solution_image_url);

    const solutionHtml = hasValidSol ? `
      <div class="solution-box">
        <div class="solution-header" style="display: flex; align-items: center; justify-content: space-between;">
          <div style="display: flex; align-items: center; gap: 0.4rem;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
            <span>Explanation &amp; Solution:</span>
          </div>
          ${q.matched_solution_file ? `<span style="font-size: 0.72rem; font-weight: 700; color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 2px 8px; border-radius: 4px;">✓ Verified with ${this.escapeHtml(q.matched_solution_file)}</span>` : ''}
        </div>
        ${rawSol ? `<div class="solution-body">${this.formatMathAndText(rawSol)}</div>` : ''}
        ${q.solution_image_url ? `
          <div style="margin-top: 0.5rem; display: flex; align-items: center; justify-content: center;">
            <img src="${this.escapeHtml(q.solution_image_url)}" alt="Solution Diagram" style="max-width: 100%; max-height: 320px; border-radius: 6px; object-fit: contain; background: #ffffff;" />
          </div>
        ` : ''}
      </div>
    ` : '';

    const diagramHtml = q.image_url ? `
      <div class="question-diagram-container">
        <div style="font-size: 0.75rem; color: #64748b; margin-bottom: 0.4rem; display: flex; align-items: center; justify-content: center; gap: 0.35rem; font-weight: 600;">
          <span>📐 Extracted Question Diagram</span>
        </div>
        <img src="${this.escapeHtml(q.image_url)}" alt="Question Diagram" />
      </div>
    ` : '';

    const typeBadgeColor = (qType === "Multiple" || qType === "MSQ") ? "background: #d1fae5; color: #047857; border-color: #a7f3d0" :
                           isNumeric ? "background: #fef3c7; color: #b45309; border-color: #fde68a" :
                           qType.toLowerCase().includes("match") ? "background: #f3e8ff; color: #7e22ce; border-color: #e9d5ff" :
                           "background: #e0e7ff; color: #4338ca; border-color: #c7d2fe";

    const diffVal = (typeof q.difficulty === "number") ? q.difficulty : 0;
    const diffBadge = diffVal === 1 
      ? `<span class="page-badge" style="background: #fee2e2; color: #b91c1c; border-color: #fca5a5; font-weight: 600;">Hard (1)</span>`
      : diffVal === -1 
      ? `<span class="page-badge" style="background: #fef3c7; color: #b45309; border-color: #fde68a; font-weight: 600;">Medium (-1)</span>`
      : `<span class="page-badge" style="background: #e0f2fe; color: #0369a1; border-color: #bae6fd; font-weight: 600;">Easy (0)</span>`;

    const questionTextContent = this.formatMathAndText(this.cleanQuestionText(q.original_question || q.translated_question || "—"));

    let chNum = q.chapter_number;
    let chName = q.chapter_name;
    if (!chNum && q.file_name) {
      const m = q.file_name.match(/(?:chapter|chp|ch|unit|પ્રકરણ|અધ્યાય|ch\.)[\s\-_]*(\d+)/i) || q.file_name.match(/^(\d+)[\s\-_.:]/) || q.file_name.match(/^(\d+)\.pdf$/i);
      if (m) chNum = m[1];
    }
    let chapterBadge = "";
    if (chNum) {
      const chLabel = chName && !chName.toLowerCase().startsWith("chapter") 
        ? `📖 Ch ${chNum}: ${this.escapeHtml(chName)}` 
        : `📖 Ch ${chNum}`;
      chapterBadge = `<span class="page-badge" style="background: #fef3c7; color: #92400e; border: 1px solid #fde68a; font-weight: 700;">${chLabel}</span>`;
    } else if (chName) {
      chapterBadge = `<span class="page-badge" style="background: #fef3c7; color: #92400e; border: 1px solid #fde68a; font-weight: 700;">📖 ${this.escapeHtml(chName)}</span>`;
    }

    const verificationBadgeHtml = hasValidSol
      ? ((q.verification_status === "verified" || q.solution_verified)
          ? `<span class="image-flag-badge" style="background: #ecfdf5; color: #047857; border-color: #a7f3d0; font-weight: 700;" title="${this.escapeHtml(q.verification_details || 'Verified Solution')}">✓ Verified Solution${q.matched_solution_file ? ` (${this.escapeHtml(q.matched_solution_file)})` : ''}</span>`
          : (q.verification_status === "matched")
          ? `<span class="image-flag-badge" style="background: #f0fdf4; color: #166534; border-color: #bbf7d0;" title="${this.escapeHtml(q.verification_details || 'Solution Paired')}">✓ Solution Paired</span>`
          : (q.verification_status === "mismatch")
          ? `<span class="image-flag-badge" style="background: #fef2f2; color: #991b1b; border-color: #fecaca;" title="${this.escapeHtml(q.verification_details || 'Verification Alert')}">⚠️ Verification Alert</span>`
          : '')
      : '';

    // Answer image is now shown inline inside the correct option box — no separate section needed
    const answerImageHtml = '';

    const answerBadgeHtml = (isNumeric || Boolean(displayAns))
      ? (displayAns ? `<div class="answer-badge" style="background: #fef3c7; color: #92400e; border-color: #fde68a;">🔢 Answer: <strong>${this.escapeHtml(displayAns)}</strong></div>` : (cleanMcqAns ? `<div class="answer-badge">✓ Answer: <strong>${this.escapeHtml(cleanMcqAns)}</strong></div>` : ''))
      : (cleanMcqAns ? `<div class="answer-badge">✓ Answer: <strong>${this.escapeHtml(cleanMcqAns)}</strong></div>` : (rawAns ? `<div class="answer-badge">✓ Answer: <strong>${this.escapeHtml(rawAns)}</strong></div>` : ''));

    const qMarks = (q.marks !== undefined && q.marks !== null && q.marks !== "") ? Number(q.marks) : 4;
    const marksBadgeHtml = `<span class="marks-badge" title="Marks: ${qMarks} (Exported to Excel)">🎯 ${qMarks} Mark${qMarks === 4 ? 's' : ''}</span>`;

    card.innerHTML = `
      <div class="mcq-card-header">
        <div class="mcq-badge-group">
          <span class="q-badge">Q ${this.escapeHtml(q.question_number)}</span>
          ${chapterBadge}
          <span class="page-badge" style="${typeBadgeColor}">${this.escapeHtml(qType)}</span>
          ${marksBadgeHtml}
          ${diffBadge}
          <span class="page-badge">Page ${q.page_number || 1}</span>
          ${q.file_name ? `<span class="page-badge">${this.escapeHtml(q.file_name)}</span>` : ''}
          ${verificationBadgeHtml}
          ${(q.has_question_image || q.image_url) ? `<span class="image-flag-badge">🖼️ Diagram</span>` : ''}
          ${q.answer_image_url ? `<span class="image-flag-badge" style="background: #ecfdf5; color: #047857; border-color: #a7f3d0;">🎯 Answer Diagram</span>` : ''}
          ${hasValidSol && (q.has_solution_image || q.solution_image_url) ? `<span class="image-flag-badge" style="background: #dcfce7; color: #15803d; border-color: #86efac;">📊 Solution Diagram</span>` : ''}
        </div>
        ${answerBadgeHtml}
      </div>

      <div class="question-text-box">
        <div class="question-text">${questionTextContent}</div>
      </div>

      ${matchingColumnsHtml}
      ${diagramHtml}
      ${optionsHtml}
      ${numericAnswerHtml}
      ${answerImageHtml}
      ${solutionHtml}
    `;

    return card;
  }

  escapeHtml(str) {
    if (!str) return "";
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  showRawJsonModal(data) {
    const formatted = JSON.stringify(data, null, 2);
    this.rawJsonContent.textContent = formatted;
    this.rawJsonModal.classList.remove("hidden");
  }

  showLiveLogsModal() {
    if (this.liveLogsModal) {
      this.liveLogsModal.classList.remove("hidden");
    }
  }

  hideLiveLogsModal() {
    if (this.liveLogsModal) {
      this.liveLogsModal.classList.add("hidden");
    }
  }

  renderLogs(logsData, searchQuery = "", activeFilter = "ALL") {
    if (!this.terminalContent) return;
    const logs = (logsData && logsData.logs) || [];
    const fileSize = (logsData && logsData.log_file_size_bytes) || 0;

    // Update file size indicator
    if (this.logFileSizeIndicator) {
      const kb = (fileSize / 1024).toFixed(1);
      this.logFileSizeIndicator.textContent = `File size: ${kb} KB`;
    }

    // Tally level counts
    let infoCount = 0;
    let warnCount = 0;
    let errCount = 0;
    logs.forEach(l => {
      const lvl = (l.level || "").toUpperCase();
      if (lvl === "INFO") infoCount++;
      else if (lvl === "WARNING" || lvl === "WARN") warnCount++;
      else if (lvl === "ERROR" || lvl === "CRITICAL") errCount++;
    });

    if (this.logCountAll) this.logCountAll.textContent = logs.length;
    if (this.logCountInfo) this.logCountInfo.textContent = infoCount;
    if (this.logCountWarn) this.logCountWarn.textContent = warnCount;
    if (this.logCountError) this.logCountError.textContent = errCount;

    // Filter by level & search text
    const query = searchQuery.trim().toLowerCase();
    const filtered = logs.filter(item => {
      const lvl = (item.level || "").toUpperCase();
      if (activeFilter !== "ALL") {
        if (activeFilter === "INFO" && lvl !== "INFO") return false;
        if (activeFilter === "WARNING" && lvl !== "WARNING" && lvl !== "WARN") return false;
        if (activeFilter === "ERROR" && lvl !== "ERROR" && lvl !== "CRITICAL") return false;
      }
      if (query) {
        const full = `${item.message || ""} ${item.logger || ""}`.toLowerCase();
        if (!full.includes(query)) return false;
      }
      return true;
    });

    if (filtered.length === 0) {
      if (this.terminalEmpty) {
        this.terminalEmpty.style.display = "block";
        this.terminalEmpty.textContent = logs.length === 0 
          ? "No logs recorded yet. Start an extraction to see live events."
          : "No logs match the current filter/search.";
      }
      this.terminalContent.innerHTML = "";
      return;
    }

    if (this.terminalEmpty) {
      this.terminalEmpty.style.display = "none";
    }

    const html = filtered.map(item => {
      const lvl = (item.level || "INFO").toUpperCase();
      let badgeClass = "level-info";
      if (lvl === "WARNING" || lvl === "WARN") badgeClass = "level-warn";
      else if (lvl === "ERROR" || lvl === "CRITICAL") badgeClass = "level-error";
      else if (lvl === "DEBUG") badgeClass = "level-debug";

      const timeStr = item.timestamp ? item.timestamp.split(" ")[1] || item.timestamp : "";
      const rawMsg = item.message || "";
      let msgClass = "term-msg";
      if (rawMsg.includes("[Scan]")) msgClass += " has-scan";
      else if (rawMsg.includes("[Hybrid Fallback]") || rawMsg.includes("[Model Switch]")) msgClass += " has-fallback";
      else if (rawMsg.includes("[ERROR]") || rawMsg.includes("[Error]")) msgClass += " has-error";

      return `<div class="terminal-line">
        <span class="term-time">${this.escapeHtml(timeStr)}</span>
        <span class="term-badge ${badgeClass}">${lvl}</span>
        <span class="term-logger">[${this.escapeHtml(item.logger || "app")}]</span>
        <span class="${msgClass}">${this.escapeHtml(rawMsg)}</span>
      </div>`;
    }).join("");

    this.terminalContent.innerHTML = html;

    if (this.logsAutoScrollCheck && this.logsAutoScrollCheck.checked && this.terminalWindow) {
      this.terminalWindow.scrollTop = this.terminalWindow.scrollHeight;
    }
  }

  showFileExportModal(targetFileName = null, results = [], onDownload) {
    this.batchResults = results;
    this.selectedTargetFile = targetFileName;

    let totalQ = 0;
    let imageQ = 0;
    let targetResults = results;

    if (targetFileName) {
      targetResults = results.filter(r => r.file_name === targetFileName);
      this.modalFileTitle.textContent = `PDF Options: ${targetFileName}`;
    } else {
      this.modalFileTitle.textContent = `Batch Export & Downloads (${results.length} PDFs)`;
    }

    targetResults.forEach(r => {
      r.questions.forEach(q => {
        totalQ++;
        if (q.has_question_image || q.image_url || q.has_solution_image || q.solution_image_url || Object.values(q.options || {}).some(opt => opt && (opt.has_image || opt.image_url))) {
          imageQ++;
        }
      });
    });

    // Summary Chips
    this.modalFileSummary.innerHTML = `
      <div class="summary-chip">📄 File(s): <strong>${targetFileName || `${results.length} Files`}</strong></div>
      <div class="summary-chip">📝 Total Questions: <strong>${totalQ}</strong></div>
      <div class="summary-chip">🖼️ With Images: <strong>${imageQ}</strong></div>
    `;

    // Processed files list
    this.modalProcessedFilesList.innerHTML = "";
    results.forEach(res => {
      const isAdvance = Boolean(res.is_advance);
      const examBadge = isAdvance
        ? `<span class="badge" style="background:#f3e8ff;color:#6b21a8;font-size:0.7rem;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;border:1px solid #d8b4fe;">JEE Adv (3 Excels)</span>`
        : `<span class="badge" style="background:#eff6ff;color:#1e40af;font-size:0.7rem;font-weight:600;padding:2px 6px;border-radius:4px;margin-left:6px;border:1px solid #bfdbfe;">JEE Main (1 Excel)</span>`;

      const row = document.createElement("div");
      row.className = "processed-file-row";
      row.innerHTML = `
        <div class="processed-file-info">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <span><strong>${this.escapeHtml(res.file_name)}</strong> (${res.total_questions} Questions) ${examBadge}</span>
        </div>
        <div class="processed-file-actions">
          <button class="btn btn-excel btn-sm file-dl-excel" title="${isAdvance ? 'Download 3 Separate Excel Files for JEE Advanced' : 'Download Excel (.xlsx) for JEE Main'}">${isAdvance ? '3 Excels (.xlsx)' : '.xlsx'}</button>
          <button class="btn btn-secondary btn-sm file-dl-csv" title="Download CSV for this file">.csv</button>
          <button class="btn btn-sm file-dl-pdf" title="Download Formatted PDF"
            style="background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;border:none;font-weight:700;border-radius:6px;padding:0.3rem 0.7rem;font-size:0.8rem;cursor:pointer;">.pdf</button>
        </div>
      `;

      row.querySelector(".file-dl-excel").addEventListener("click", () => onDownload("excel", res.file_name));
      row.querySelector(".file-dl-csv").addEventListener("click", () => onDownload("csv", res.file_name));
      const rowPdfBtn = row.querySelector(".file-dl-pdf");
      if (rowPdfBtn) rowPdfBtn.addEventListener("click", () => onDownload("pdf", res.file_name));

      this.modalProcessedFilesList.appendChild(row);
    });

    this.fileExportModal.classList.remove("hidden");
  }

  openTokenLoadingModal() {
    this.tokenLoadingSpinner.classList.remove("hidden");
    this.tokenReportContent.classList.add("hidden");
    this.tokenModal.classList.remove("hidden");
  }

  showTokenReport(report) {
    this.tokenLoadingSpinner.classList.add("hidden");
    this.tokenReportContent.classList.remove("hidden");

    if (report.is_batch && report.files && report.files.length > 1) {
      // Batch Multiple PDFs Report View
      let fileRowsHtml = report.files.map((f, idx) => `
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 0.5rem 0.6rem; font-weight: 600; color: #0f172a;">
            ${idx + 1}. ${this.escapeHtml(f.file_name)}
            <div style="font-size: 0.7rem; color: #64748b; font-weight: 400;">${f.total_pages} pages • ${f.file_size_mb} MB</div>
          </td>
          <td style="padding: 0.5rem 0.6rem; text-align: right; color: #1d4ed8; font-weight: 600;">${(f.input_tokens || 0).toLocaleString()}</td>
          <td style="padding: 0.5rem 0.6rem; text-align: right; color: #a21caf;">${(f.estimated_output_tokens || 0).toLocaleString()}</td>
          <td style="padding: 0.5rem 0.6rem; text-align: right; color: #15803d; font-weight: 700;">${(f.total_tokens || 0).toLocaleString()}</td>
          <td style="padding: 0.5rem 0.6rem; text-align: right; color: #b45309; font-weight: 700;">₹${f.total_cost_inr} <span style="font-size: 0.7rem; color: #64748b;">($${f.total_cost_usd})</span></td>
        </tr>
      `).join("");

      this.tokenReportContent.innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; margin-bottom: 1.25rem;">
          <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem;">
            <div style="font-size: 0.75rem; color: #64748b; font-weight: 600;">Batch Documents</div>
            <div style="font-size: 1.1rem; font-weight: 800; color: #0f172a; margin-top: 0.2rem;">📁 ${report.total_files} PDF Files</div>
            <div style="font-size: 0.75rem; color: #64748b; margin-top: 0.2rem;">${report.total_pages} Combined Pages (${report.total_size_mb} MB)</div>
          </div>
          <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem;">
            <div style="font-size: 0.75rem; color: #64748b; font-weight: 600;">Model &amp; API</div>
            <div style="font-size: 1.05rem; font-weight: 700; color: #4338ca; margin-top: 0.2rem;">${this.escapeHtml(report.model_name)}</div>
            <div style="font-size: 0.75rem; color: #64748b; margin-top: 0.2rem;">${this.escapeHtml(report.api_provider)}</div>
            <div style="font-size: 0.72rem; color: #047857; font-weight: 700; margin-top: 0.15rem;">₹${report.usd_to_inr_rate || '?'}/$ <span style="font-size: 0.65rem; color: #16a34a;">(Live Rate)</span></div>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.75rem; margin-bottom: 1.25rem;">
          <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 0.75rem; text-align: center;">
            <div style="font-size: 0.75rem; color: #1e40af; font-weight: 600;">Combined Input</div>
            <div style="font-size: 1.25rem; font-weight: 800; color: #1d4ed8; margin-top: 0.2rem;">${(report.input_tokens || 0).toLocaleString()}</div>
          </div>
          <div style="background: #fdf4ff; border: 1px solid #f5d0fe; border-radius: 8px; padding: 0.75rem; text-align: center;">
            <div style="font-size: 0.75rem; color: #86198f; font-weight: 600;">Est. Output</div>
            <div style="font-size: 1.25rem; font-weight: 800; color: #a21caf; margin-top: 0.2rem;">${(report.estimated_output_tokens || 0).toLocaleString()}</div>
          </div>
          <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 0.75rem; text-align: center;">
            <div style="font-size: 0.75rem; color: #166534; font-weight: 600;">Grand Total Tokens</div>
            <div style="font-size: 1.25rem; font-weight: 800; color: #15803d; margin-top: 0.2rem;">${(report.total_tokens || 0).toLocaleString()}</div>
          </div>
          <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 0.75rem; text-align: center;">
            <div style="font-size: 0.75rem; color: #92400e; font-weight: 600;">Total Estimated Cost</div>
            <div style="font-size: 1.15rem; font-weight: 800; color: #b45309; margin-top: 0.2rem;">$${report.total_cost_usd} USD</div>
            <div style="font-size: 0.75rem; font-weight: 700; color: #047857;">(₹${report.total_cost_inr} INR)</div>
          </div>
        </div>

        <div style="font-size: 0.85rem; font-weight: 700; color: #334155; margin-bottom: 0.4rem;">📑 Per-File Token Breakdown:</div>
        <div style="max-height: 250px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 6px;">
          <table style="width: 100%; border-collapse: collapse; font-size: 0.8rem;">
            <thead style="background: #f1f5f9; position: sticky; top: 0;">
              <tr>
                <th style="padding: 0.5rem 0.6rem; text-align: left; color: #475569;">File Name</th>
                <th style="padding: 0.5rem 0.6rem; text-align: right; color: #475569;">Input Tokens</th>
                <th style="padding: 0.5rem 0.6rem; text-align: right; color: #475569;">Output</th>
                <th style="padding: 0.5rem 0.6rem; text-align: right; color: #475569;">Total Tokens</th>
                <th style="padding: 0.5rem 0.6rem; text-align: right; color: #475569;">Cost</th>
              </tr>
            </thead>
            <tbody>
              ${fileRowsHtml}
            </tbody>
          </table>
        </div>
        <div style="margin-top: 0.75rem; font-size: 0.75rem; color: #16a34a; background: #f0fdf4; padding: 0.5rem; border-radius: 4px; border: 1px solid #dcfce7;">
          💡 <strong>Gemini Free Tier:</strong> 15 Requests Per Minute (RPM) are 100% Free of charge!
        </div>
      `;
      return;
    }

    // Single PDF Report View
    let pageRowsHtml = "";
    if (report.page_breakdowns && report.page_breakdowns.length > 0) {
      pageRowsHtml = report.page_breakdowns.map(p => `
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 0.4rem 0.6rem; font-weight: 600; color: #0f172a;">Page ${p.page}</td>
          <td style="padding: 0.4rem 0.6rem; text-align: center; color: #4338ca; font-weight: 600;">${p.detected_questions !== undefined ? p.detected_questions : '-'}</td>
          <td style="padding: 0.4rem 0.6rem; text-align: right; color: #1d4ed8; font-weight: 600;">${(p.input_tokens || 0).toLocaleString()}</td>
          <td style="padding: 0.4rem 0.6rem; text-align: right; color: #a21caf;">${(p.output_tokens || 0).toLocaleString()}</td>
          <td style="padding: 0.4rem 0.6rem; text-align: right; color: #15803d; font-weight: 700;">${(p.total_tokens || 0).toLocaleString()}</td>
          <td style="padding: 0.4rem 0.6rem; text-align: right; color: #b45309; font-weight: 700;">₹${p.cost_inr !== undefined ? p.cost_inr : '0.00'}</td>
        </tr>
      `).join("");
    }

    this.tokenReportContent.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.75rem; margin-bottom: 1.25rem;">
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem;">
          <div style="font-size: 0.75rem; color: #64748b; font-weight: 600;">PDF Document</div>
          <div style="font-size: 0.95rem; font-weight: 700; color: #0f172a; margin-top: 0.2rem; word-break: break-all;">${this.escapeHtml(report.file_name)}</div>
          <div style="font-size: 0.75rem; color: #64748b; margin-top: 0.2rem;">${report.total_pages} Page${report.total_pages === 1 ? '' : 's'} (${report.file_size_mb} MB)</div>
        </div>
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0.75rem;">
          <div style="font-size: 0.75rem; color: #64748b; font-weight: 600;">Model &amp; Pricing</div>
          <div style="font-size: 0.95rem; font-weight: 700; color: #4338ca; margin-top: 0.2rem;">${this.escapeHtml(report.model_name)}</div>
          <div style="font-size: 0.72rem; color: #64748b; margin-top: 0.2rem;">
            In: $${report.pricing_rates ? report.pricing_rates.input : '?'}/1M • Out: $${report.pricing_rates ? report.pricing_rates.output : '?'}/1M
            &nbsp;•&nbsp; <span style="color: #047857; font-weight: 700;">₹${report.usd_to_inr_rate || '?'}/$</span> <span style="font-size: 0.65rem; color: #16a34a;">(Live)</span>
          </div>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.75rem; margin-bottom: 1.25rem;">
        <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 0.75rem; text-align: center;">
          <div style="font-size: 0.72rem; color: #1e40af; font-weight: 600;">Input Tokens</div>
          <div style="font-size: 1.2rem; font-weight: 800; color: #1d4ed8; margin-top: 0.2rem;">${(report.input_tokens || 0).toLocaleString()}</div>
        </div>
        <div style="background: #fdf4ff; border: 1px solid #f5d0fe; border-radius: 8px; padding: 0.75rem; text-align: center;">
          <div style="font-size: 0.72rem; color: #86198f; font-weight: 600;">Est. Output</div>
          <div style="font-size: 1.2rem; font-weight: 800; color: #a21caf; margin-top: 0.2rem;">${(report.estimated_output_tokens || 0).toLocaleString()}</div>
        </div>
        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 0.75rem; text-align: center;">
          <div style="font-size: 0.72rem; color: #166534; font-weight: 600;">Total Tokens</div>
          <div style="font-size: 1.2rem; font-weight: 800; color: #15803d; margin-top: 0.2rem;">${(report.total_tokens || 0).toLocaleString()}</div>
        </div>
        <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 0.75rem; text-align: center;">
          <div style="font-size: 0.72rem; color: #92400e; font-weight: 600;">Estimated Cost</div>
          <div style="font-size: 1.1rem; font-weight: 800; color: #b45309; margin-top: 0.2rem;">$${report.total_cost_usd} USD</div>
          <div style="font-size: 0.75rem; font-weight: 700; color: #047857;">(₹${report.total_cost_inr} INR)</div>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
        <div style="font-size: 0.85rem; font-weight: 700; color: #334155;">📄 Accurate Per-Page Token &amp; Cost Details:</div>
        <div style="font-size: 0.72rem; color: #64748b;">${report.total_pages} Pages Scanned</div>
      </div>
      <div style="max-height: 230px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 6px;">
        <table style="width: 100%; border-collapse: collapse; font-size: 0.78rem;">
          <thead style="background: #f1f5f9; position: sticky; top: 0;">
            <tr>
              <th style="padding: 0.45rem 0.6rem; text-align: left; color: #475569;">Page #</th>
              <th style="padding: 0.45rem 0.6rem; text-align: center; color: #475569;">Questions</th>
              <th style="padding: 0.45rem 0.6rem; text-align: right; color: #475569;">Input Tokens</th>
              <th style="padding: 0.45rem 0.6rem; text-align: right; color: #475569;">Est. Output</th>
              <th style="padding: 0.45rem 0.6rem; text-align: right; color: #475569;">Total Tokens</th>
              <th style="padding: 0.45rem 0.6rem; text-align: right; color: #475569;">Cost (₹)</th>
            </tr>
          </thead>
          <tbody>
            ${pageRowsHtml}
          </tbody>
        </table>
      </div>
      <div style="margin-top: 0.75rem; font-size: 0.75rem; color: #16a34a; background: #f0fdf4; padding: 0.5rem; border-radius: 4px; border: 1px solid #dcfce7; display: flex; justify-content: space-between; align-items: center;">
        <span>💡 <strong>Gemini Free Tier:</strong> 15 Requests Per Minute (RPM) are <strong>100% Free (₹0.00)</strong>!</span>
        <span style="font-weight: 600; color: #15803d;">Original API Rates</span>
      </div>
    `;
  }

  showTokenError(errMessage) {
    this.tokenLoadingSpinner.classList.add("hidden");
    this.tokenReportContent.classList.remove("hidden");
    this.tokenReportContent.innerHTML = `
      <div style="padding: 1.5rem; text-align: center; color: #b91c1c; background: #fee2e2; border-radius: 8px; border: 1px solid #fca5a5;">
        <div style="font-weight: 700; font-size: 1rem; margin-bottom: 0.35rem;">Failed to calculate tokens</div>
        <div style="font-size: 0.85rem;">${this.escapeHtml(errMessage)}</div>
      </div>
    `;
  }

  updateQuotaDisplay(data) {
    if (!data) return;
    const pct = typeof data.percent_remaining === "number" ? data.percent_remaining : 100.0;
    const pctStr = `${pct.toFixed(0)}%`;

    if (this.quotaPercentLabel) {
      this.quotaPercentLabel.textContent = `${pctStr} Available`;
    }
    if (this.quotaMiniBar) {
      this.quotaMiniBar.style.width = `${Math.max(2, Math.min(100, pct))}%`;
    }

    if (this.quotaPill) {
      this.quotaPill.className = "quota-pill";
      if (pct < 20) {
        this.quotaPill.classList.add("danger");
      } else if (pct < 50) {
        this.quotaPill.classList.add("warning");
      }
      const resetInfo = data.reset_in_human ? ` • Resets in ${data.reset_in_human}` : "";
      this.quotaPill.title = `API Quota: ${pctStr} Available (${(data.requests_used_today || 0)} used, ${(data.requests_remaining || 0).toLocaleString()} of ${(data.total_daily_limit || 1500).toLocaleString()} remaining)${resetInfo}`;
    }

    // Update modal elements if present
    if (this.quotaModalPercent) {
      this.quotaModalPercent.textContent = pctStr;
    }
    if (this.quotaCircle) {
      this.quotaCircle.className = "quota-percent-circle";
      if (pct < 20) this.quotaCircle.classList.add("danger");
      else if (pct < 50) this.quotaCircle.classList.add("warning");
    }

    if (this.qStatTotalLimit) {
      this.qStatTotalLimit.textContent = `${(data.total_daily_limit || 1500).toLocaleString()} RPD`;
    }
    if (this.qStatUsedRequests) {
      this.qStatUsedRequests.textContent = (data.requests_used_today || 0).toLocaleString();
    }
    if (this.qStatRemainingRequests) {
      this.qStatRemainingRequests.textContent = (data.requests_remaining || 0).toLocaleString();
    }
    if (this.qStatTokensToday) {
      const totTokens = (data.total_tokens_today || 0).toLocaleString();
      const inrSaved = ((data.total_tokens_today || 0) * 0.000007).toFixed(2);
      this.qStatTokensToday.textContent = `${totTokens} (~₹${inrSaved} saved)`;
    }
    if (this.qStatKeysCount) {
      const kCount = data.api_keys_configured || data.api_keys_count || 1;
      this.qStatKeysCount.textContent = `${kCount} Key${kCount === 1 ? '' : 's'} (${kCount * 1500} RPD Total)`;
    }
    if (this.qStatResetCountdown) {
      if (data.reset_in_human) {
        this.qStatResetCountdown.textContent = `${data.reset_in_human} (at 00:00 UTC)`;
      } else {
        this.qStatResetCountdown.textContent = "Daily Midnight UTC";
      }
    }
    if (this.quotaBarRemainingLabel) {
      this.quotaBarRemainingLabel.textContent = `${pctStr} Available`;
    }
    if (this.quotaBarMaxLabel) {
      this.quotaBarMaxLabel.textContent = `${(data.total_daily_limit || 1500).toLocaleString()} Max`;
    }
    if (this.quotaModalBarFill) {
      this.quotaModalBarFill.style.width = `${Math.max(2, Math.min(100, pct))}%`;
      this.quotaModalBarFill.className = "quota-bar-fill";
      if (pct < 20) this.quotaModalBarFill.classList.add("danger");
      else if (pct < 50) this.quotaModalBarFill.classList.add("warning");
    }

    // Render model status cards in modal
    if (this.quotaModelsGrid && data.models) {
      this.renderQuotaModels(data.models, data.reset_in_human);
    }

    // Dynamically update model selector dropdown with remaining percent limit for each model
    const modelSelector = document.getElementById("modelSelector");
    if (modelSelector && data.models) {
      const modelLabels = {
        "gemini-3.5-flash": { name: "Gemini 3.5 Flash", icon: "⚡", note: "Recommended" },
        "gemini-3.6-flash": { name: "Gemini 3.6 Flash", icon: "⚡", note: "Next-Gen" },
        "gemini-3.7-flash": { name: "Gemini 3.7 Flash", icon: "⚡", note: "Hybrid" },
        "gemini-3.7-flash-lite": { name: "Gemini 3.7 Flash-Lite", icon: "⚡", note: "Fast Hybrid" },
        "gemini-3.5-flash-lite": { name: "Gemini 3.5 Flash-Lite", icon: "⚡", note: "Lite" },
        "gemini-3.1-pro": { name: "Gemini 3.1 Pro", icon: "🧠", note: "Deep Reasoning" },
        "gemini-3.1-flash-lite": { name: "Gemini 3.1 Flash-Lite", icon: "⚡", note: "Ultra Fast" },
        "gemini-2.5-flash": { name: "Gemini 2.5 Flash", icon: "⚡", note: "Fast" },
        "gemini-2.5-pro": { name: "Gemini 2.5 Pro", icon: "🧠", note: "Deep Math" },
        "gemini-2.0-flash": { name: "Gemini 2.0 Flash", icon: "⚡", note: "High Speed" },
        "gemini-2.0-flash-lite": { name: "Gemini 2.0 Flash-Lite", icon: "⚡", note: "Lite" },
        "gemini-1.5-flash": { name: "Gemini 1.5 Flash", icon: "⚡", note: "High Quota" },
        "gemini-1.5-pro": { name: "Gemini 1.5 Pro", icon: "🧠", note: "Reasoning" },
        "gemma-4-26b-a4b-it": { name: "Gemma 4 26B A4B", icon: "💎", note: "MoE Multimodal" },
        "gemma-4-31b-it": { name: "Gemma 4 31B", icon: "💎", note: "Multimodal" }
      };

      for (let i = 0; i < modelSelector.options.length; i++) {
        const opt = modelSelector.options[i];
        const mKey = opt.value;
        const mInfo = data.models[mKey];
        const meta = modelLabels[mKey] || { name: mKey, icon: "⚡", note: "" };

        if (mInfo) {
          const mPct = typeof mInfo.percent_remaining === "number" ? mInfo.percent_remaining : 100.0;
          const rem = (mInfo.requests_remaining !== undefined ? mInfo.requests_remaining : (mInfo.daily_limit || 1500));
          const lim = mInfo.daily_limit || 1500;

          if (mInfo.badge === "exhausted") {
            opt.textContent = `⛔ ${meta.name} — 0% Available (Daily Limit Hit)`;
          } else if (mInfo.badge === "rate_limited") {
            opt.textContent = `⚠️ ${meta.name} — ${mPct.toFixed(0)}% Available (Rate Limited)`;
          } else {
            opt.textContent = `${meta.icon} ${meta.name} (${mPct.toFixed(0)}% Available · ${rem.toLocaleString()}/${lim.toLocaleString()} RPD)`;
          }
        }
      }
    }
  }

  renderQuotaModels(models, resetInHuman = "") {
    if (!this.quotaModelsGrid || !models) return;
    this.quotaModelsGrid.innerHTML = "";
    
    const modelMeta = {
      "gemini-3.5-flash": { name: "Gemini 3.5 Flash", icon: "⚡", desc: "Recommended · Fast, Highly Accurate & High Quota (1,500 RPD Free)" },
      "gemini-3.6-flash": { name: "Gemini 3.6 Flash", icon: "⚡", desc: "Next-Gen High-Speed Multimodal Intelligence" },
      "gemini-3.7-flash": { name: "Gemini 3.7 Flash", icon: "⚡", desc: "Hybrid Reasoning & Speed Multimodal Model" },
      "gemini-3.7-flash-lite": { name: "Gemini 3.7 Flash-Lite", icon: "⚡", desc: "Ultra-Fast Hybrid Flash-Lite Model" },
      "gemini-3.5-flash-lite": { name: "Gemini 3.5 Flash-Lite", icon: "⚡", desc: "Lightweight High-Throughput Model" },
      "gemini-3.1-pro": { name: "Gemini 3.1 Pro", icon: "🧠", desc: "Deep Reasoning Multimodal Pro Model (High Complexity)" },
      "gemini-3.1-flash-lite": { name: "Gemini 3.1 Flash-Lite", icon: "⚡", desc: "Ultra-Fast Flash-Lite Model" },
      "gemini-2.5-flash": { name: "Gemini 2.5 Flash", icon: "⚡", desc: "High-Speed Multimodal Production Model" },
      "gemini-2.5-pro": { name: "Gemini 2.5 Pro", icon: "🧠", desc: "Advanced Multimodal Pro Model with Deep Math & LaTeX reasoning" },
      "gemini-2.0-flash": { name: "Gemini 2.0 Flash", icon: "⚡", desc: "Fast & Stable Standard Flash Model" },
      "gemini-2.0-flash-lite": { name: "Gemini 2.0 Flash-Lite", icon: "⚡", desc: "Lightweight High-Throughput Model" },
      "gemini-1.5-flash": { name: "Gemini 1.5 Flash", icon: "⚡", desc: "Classic High-Quota Multimodal Model" },
      "gemini-1.5-pro": { name: "Gemini 1.5 Pro", icon: "🧠", desc: "Classic Complex Reasoning Pro Model" },
      "gemma-4-26b-a4b-it": { name: "Gemma 4 26B A4B", icon: "💎", desc: "Google DeepMind MoE Multimodal Fallback (256k Context)" },
      "gemma-4-31b-it": { name: "Gemma 4 31B", icon: "💎", desc: "Open-Weight Multimodal Model" }
    };

    Object.entries(models).forEach(([modelName, info]) => {
      const card = document.createElement("div");
      card.className = "quota-model-card";
      const meta = modelMeta[modelName] || { name: modelName, icon: "🤖", desc: "" };
      const pct = typeof info.percent_remaining === "number" ? info.percent_remaining : 100.0;
      const pctStr = `${pct.toFixed(0)}%`;
      
      let pctClass = "";
      if (pct < 20 || info.badge === "exhausted") pctClass = "danger";
      else if (pct < 50 || info.badge === "rate_limited") pctClass = "warning";

      let statusLabel = info.status;
      if (info.badge === "exhausted" && resetInHuman) {
        statusLabel = `Hit (Resets in ${resetInHuman})`;
      }

      card.innerHTML = `
        <div class="model-card-header">
          <div style="display: flex; align-items: center; gap: 0.4rem;">
            <span style="font-size: 1.1rem;">${meta.icon}</span>
            <div>
              <div class="model-card-name">${this.escapeHtml(meta.name)}</div>
              <div style="font-size: 0.7rem; color: #64748b;">${this.escapeHtml(meta.desc)}</div>
            </div>
          </div>
          <div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 2px;">
            <span class="model-card-pct-badge ${pctClass}">${pctStr} Remaining</span>
            <span class="model-card-badge ${info.badge}">${this.escapeHtml(statusLabel)}</span>
          </div>
        </div>

        <div class="model-card-bar-track">
          <div class="model-card-bar-fill ${pctClass}" style="width: ${Math.max(2, Math.min(100, pct))}%;"></div>
        </div>

        <div class="model-card-meta" style="margin-top: 0.5rem;">
          <span>Remaining: <strong>${(info.requests_remaining !== undefined ? info.requests_remaining : (info.daily_limit || 1500)).toLocaleString()} / ${(info.daily_limit || 1500).toLocaleString()} RPD</strong></span>
          <span>Calls Today: <strong>${(info.calls_today || 0).toLocaleString()}</strong></span>
        </div>
      `;
      this.quotaModelsGrid.appendChild(card);
    });
  }

  showQuotaTestLoading() {
    if (!this.quotaTestResultBox) return;
    this.quotaTestResultBox.className = "quota-test-result";
    this.quotaTestResultBox.classList.remove("hidden");
    this.quotaTestResultBox.innerHTML = `
      <div style="display: flex; align-items: center; gap: 0.5rem; color: #4338ca;">
        <span class="spinner-small" style="width: 14px; height: 14px; border-width: 2px;"></span>
        <span>Pinging Google Gemini API to verify live quota...</span>
      </div>
    `;
  }

  showQuotaTestResult(result) {
    if (!this.quotaTestResultBox) return;
    this.quotaTestResultBox.classList.remove("hidden");
    if (result && result.success) {
      this.quotaTestResultBox.className = "quota-test-result success";
      this.quotaTestResultBox.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.4rem; font-weight: 700; margin-bottom: 0.25rem;">
          <span>✅ API Key Active &amp; Ready</span>
          <span style="font-size: 0.75rem; background: #dcfce7; color: #166534; padding: 0.1rem 0.4rem; border-radius: 4px;">${result.latency_ms}ms</span>
        </div>
        <div>${this.escapeHtml(result.message || 'Connectivity verified.')} Model: <strong>${this.escapeHtml(result.model)}</strong></div>
      `;
    } else {
      this.quotaTestResultBox.className = "quota-test-result error";
      this.quotaTestResultBox.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.4rem; font-weight: 700; margin-bottom: 0.25rem;">
          <span>⚠️ Quota / Key Alert</span>
          <span style="font-size: 0.75rem; background: #fee2e2; color: #991b1b; padding: 0.1rem 0.4rem; border-radius: 4px;">${this.escapeHtml(result ? result.status : 'error')}</span>
        </div>
        <div>${this.escapeHtml(result ? result.message : 'Failed to connect to Gemini API.')}</div>
      `;
    }
  }

  showToast(message, type = "info", duration = 4500) {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 999999;
        display: flex;
        flex-direction: column;
        gap: 10px;
        max-width: 420px;
        pointer-events: none;
      `;
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `custom-toast toast-${type}`;
    
    // Type colors and icons
    let bg = "#1e293b";
    let border = "#334155";
    let icon = "ℹ️";
    let textColor = "#f8fafc";
    
    if (type === "success") {
      bg = "linear-gradient(135deg, #065f46 0%, #047857 100%)";
      border = "#10b981";
      icon = "✅";
    } else if (type === "warning") {
      bg = "linear-gradient(135deg, #78350f 0%, #b45309 100%)";
      border = "#f59e0b";
      icon = "⚠️";
    } else if (type === "error") {
      bg = "linear-gradient(135deg, #7f1d1d 0%, #b91c1c 100%)";
      border = "#ef4444";
      icon = "❌";
    } else {
      bg = "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)";
      border = "#6366f1";
      icon = "ℹ️";
    }

    toast.style.cssText = `
      background: ${bg};
      color: ${textColor};
      border: 1px solid ${border};
      padding: 12px 16px;
      border-radius: 10px;
      font-size: 0.88rem;
      font-weight: 500;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
      display: flex;
      align-items: center;
      gap: 12px;
      pointer-events: auto;
      transform: translateY(20px);
      opacity: 0;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      cursor: pointer;
      backdrop-filter: blur(8px);
      word-break: break-word;
    `;

    toast.innerHTML = `
      <span style="font-size: 1.1rem; flex-shrink: 0;">${icon}</span>
      <div style="flex: 1; line-height: 1.4;">${this.escapeHtml(message)}</div>
      <button style="background: transparent; border: none; color: rgba(255,255,255,0.7); font-size: 1.2rem; cursor: pointer; padding: 0 4px; line-height: 1;" title="Dismiss">&times;</button>
    `;

    const closeBtn = toast.querySelector("button");
    const removeToast = () => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px) scale(0.95)";
      setTimeout(() => {
        if (toast.parentElement) toast.parentElement.removeChild(toast);
      }, 300);
    };

    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeToast();
    });
    toast.addEventListener("click", removeToast);

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
      toast.style.opacity = "1";
      toast.style.transform = "translateY(0)";
    });

    // Auto remove after duration
    if (duration > 0) {
      setTimeout(() => {
        if (toast.parentElement) removeToast();
      }, duration);
    }
  }
}

window.UIManager = UIManager;

