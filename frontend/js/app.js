/**
 * Application Controller & API Integration Module
 */

document.addEventListener("DOMContentLoaded", () => {
  const ui = new UIManager();

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const startExtractionBtn = document.getElementById("startExtractionBtn");
  const checkTokensBtn = document.getElementById("checkTokensBtn");

  // Solution PDF elements
  const solutionDropzone = document.getElementById("solutionDropzone");
  const solutionFileInput = document.getElementById("solutionFileInput");
  const solutionFileBadge = document.getElementById("solutionFileBadge");
  const solutionFileInfo = document.getElementById("solutionFileInfo");
  const solutionFileCount = document.getElementById("solutionFileCount");
  const solutionFileList = document.getElementById("solutionFileList");
  const clearSolutionBtn = document.getElementById("clearSolutionBtn");

  // Textbook PDF elements (Topic & Chapter Structure)
  const textbookDropzone = document.getElementById("textbookDropzone");
  const textbookFileInput = document.getElementById("textbookFileInput");
  const textbookFileInfo = document.getElementById("textbookFileInfo");
  const textbookFileName = document.getElementById("textbookFileName");
  const textbookFileCount = document.getElementById("textbookFileCount");
  const textbookFileList = document.getElementById("textbookFileList");
  const clearTextbookBtn = document.getElementById("clearTextbookBtn");

  // Model status panel elements
  const activeModelLabel = document.getElementById("activeModelLabel");
  const pageStatusLabel = document.getElementById("pageStatusLabel");
  const questionsFoundLabel = document.getElementById("questionsFoundLabel");
  const modelSwitchBanner = document.getElementById("modelSwitchBanner");
  const partialDownloadBanner = document.getElementById("partialDownloadBanner");
  const partialDownloadExcelBtn = document.getElementById("partialDownloadExcelBtn");

  // App State
  let selectedFiles = [];
  let textbookFiles = [];        // Optional textbook PDF files (multiple allowed)
  let solutionFiles = [];        // Optional solution PDF files (multiple allowed)
  let currentJobId = null;
  let batchResults = [];
  let pollInterval = null;
  let apiKey = localStorage.getItem("gemini_api_key") || "";
  let lastKnownModelStatus = "";  // Track model status changes for banner display

  const API_BASE = typeof CONFIG !== "undefined" && CONFIG.API_BASE_URL 
    ? CONFIG.API_BASE_URL 
    : "";

  // Set window helper for solution file removal
  window.removeSolutionFileFromList = function(idx) {
    removeSolutionFile(idx);
  };
  window.removeTextbookFileFromList = function(idx) {
    removeTextbookFile(idx);
  };

  // 1. Initial Health Check & Quota Status
  async function checkBackendHealth() {
    try {
      const res = await fetch(`${API_BASE}/api/health`);
      if (res.ok) {
        const data = await res.json();
        const hasKey = Boolean(apiKey || data.api_key_configured);
        ui.setBackendStatus(true, hasKey);
      } else {
        ui.setBackendStatus(false, false);
      }
    } catch (err) {
      ui.setBackendStatus(false, false);
    }
  }

  async function fetchQuotaStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/quota-status`);
      if (res.ok) {
        const data = await res.json();
        ui.updateQuotaDisplay(data);
      }
    } catch (e) {
      console.warn("Could not fetch quota status:", e);
    }
  }

  checkBackendHealth();
  fetchQuotaStatus();
  setInterval(() => {
    checkBackendHealth();
    fetchQuotaStatus();
  }, 15000);

  // Clear all previous files and results on page reload/startup
  selectedFiles = [];
  batchResults = [];
  currentJobId = null;
  localStorage.removeItem("last_selected_files");
  localStorage.removeItem("last_job_id");
  if (fileInput) fileInput.value = "";
  ui.renderFileList([], removeFile, openFileOptions);
  ui.updateStats([]);
  ui.showProgress(false);
  if (startExtractionBtn) startExtractionBtn.disabled = false;
  if (checkTokensBtn) checkTokensBtn.disabled = false;

  // 2. File Dropzone & Selection Handling
  function handleFiles(files) {
    const pdfs = (files || []).filter(f => f.name && f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) {
      alert("Please select valid PDF file(s).");
      return;
    }
    pdfs.forEach(file => {
      if (!selectedFiles.some(f => f.name === file.name)) {
        selectedFiles.push(file);
      }
    });
    ui.renderFileList(selectedFiles, removeFile, openFileOptions);
    if (startExtractionBtn) startExtractionBtn.disabled = selectedFiles.length === 0;
    if (checkTokensBtn) checkTokensBtn.disabled = selectedFiles.length === 0;
  }

  if (dropzone && fileInput) {
    dropzone.addEventListener("click", (e) => {
      if (e.target !== fileInput) {
        fileInput.click();
      }
    });

    ["dragenter", "dragover"].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
      });
    });

    ["dragleave", "drop"].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleFiles(Array.from(e.dataTransfer.files));
      }
    });

    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files.length > 0) {
        handleFiles(Array.from(fileInput.files));
        fileInput.value = "";
      }
    });
  }

  // 2a. Solution PDF Dropzone Handlers (Supports Multiple Solution Files)
  if (solutionDropzone && solutionFileInput) {
    solutionDropzone.addEventListener("click", (e) => {
      if (e.target !== solutionFileInput && !e.target.closest("button")) {
        solutionFileInput.click();
      }
    });

    ["dragenter", "dragover"].forEach(ev => {
      solutionDropzone.addEventListener(ev, e => {
        e.preventDefault();
        solutionDropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(ev => {
      solutionDropzone.addEventListener(ev, e => {
        e.preventDefault();
        solutionDropzone.classList.remove("dragover");
      });
    });
    solutionDropzone.addEventListener("drop", e => {
      e.preventDefault();
      solutionDropzone.classList.remove("dragover");
      const dropped = Array.from(e.dataTransfer?.files || []).filter(f => f.name.toLowerCase().endsWith(".pdf"));
      if (dropped.length > 0) addSolutionFiles(dropped);
    });
    solutionFileInput.addEventListener("change", () => {
      const selected = Array.from(solutionFileInput.files || []).filter(f => f.name.toLowerCase().endsWith(".pdf"));
      if (selected.length > 0) addSolutionFiles(selected);
      solutionFileInput.value = "";
    });
    if (clearSolutionBtn) {
      clearSolutionBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        solutionFiles = [];
        renderSolutionFiles();
      });
    }
  }

  function addSolutionFiles(newFiles) {
    let added = 0;
    for (const f of newFiles) {
      if (!solutionFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
        solutionFiles.push(f);
        added++;
      }
    }
    renderSolutionFiles();
    if (added > 0) {
      ui.showToast(`Attached ${added} solution PDF(s) (Total: ${solutionFiles.length})`, "info");
    }
  }

  function removeSolutionFile(idx) {
    if (idx >= 0 && idx < solutionFiles.length) {
      const removed = solutionFiles.splice(idx, 1);
      renderSolutionFiles();
      if (removed.length > 0) {
        ui.showToast(`Removed solution: ${removed[0].name}`, "info");
      }
    }
  }

  function renderSolutionFiles() {
    if (!solutionFileInfo) return;
    if (solutionFiles.length === 0) {
      solutionFileInfo.classList.add("hidden");
      if (solutionFileCount) solutionFileCount.textContent = "Solutions (0):";
      if (solutionFileList) solutionFileList.innerHTML = "";
      return;
    }
    solutionFileInfo.classList.remove("hidden");
    if (solutionFileCount) solutionFileCount.textContent = `Solutions (${solutionFiles.length}):`;
    if (solutionFileList) {
      solutionFileList.innerHTML = solutionFiles.map((f, idx) => `
        <span style="display:inline-flex; align-items:center; gap:0.25rem; background:#e0f2fe; color:#0369a1; padding:0.15rem 0.4rem; border-radius:4px; font-size:0.72rem; border:1px solid #bae6fd; max-width:200px;" title="${f.name}">
          <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${f.name}</span>
          <button type="button" onclick="window.removeSolutionFileFromList(${idx})" style="background:none; border:none; color:#ef4444; font-weight:700; cursor:pointer; padding:0; line-height:1; font-size:0.75rem;">✕</button>
        </span>
      `).join("");
    }
  }

  // 2b. Textbook PDF Dropzone Handlers (Supports Multiple Textbooks)
  if (textbookDropzone && textbookFileInput) {
    textbookDropzone.addEventListener("click", (e) => {
      if (e.target !== textbookFileInput && !e.target.closest("button")) {
        textbookFileInput.click();
      }
    });

    ["dragenter", "dragover"].forEach(ev => {
      textbookDropzone.addEventListener(ev, e => {
        e.preventDefault();
        textbookDropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(ev => {
      textbookDropzone.addEventListener(ev, e => {
        e.preventDefault();
        textbookDropzone.classList.remove("dragover");
      });
    });
    textbookDropzone.addEventListener("drop", e => {
      const dropped = Array.from(e.dataTransfer?.files || []).filter(f => f.name.toLowerCase().endsWith(".pdf"));
      if (dropped.length > 0) addTextbookFiles(dropped);
    });
    textbookFileInput.addEventListener("change", () => {
      const selected = Array.from(textbookFileInput.files || []).filter(f => f.name.toLowerCase().endsWith(".pdf"));
      if (selected.length > 0) addTextbookFiles(selected);
      textbookFileInput.value = "";
    });
    if (clearTextbookBtn) {
      clearTextbookBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        textbookFiles = [];
        renderTextbookFiles();
      });
    }
  }

  function addTextbookFiles(newFiles) {
    let added = 0;
    for (const f of newFiles) {
      if (!textbookFiles.some(existing => existing.name === f.name && existing.size === f.size)) {
        textbookFiles.push(f);
        added++;
      }
    }
    renderTextbookFiles();
    if (added > 0) {
      ui.showToast(`Attached ${added} textbook PDF(s) (Total: ${textbookFiles.length})`, "info");
    }
  }

  function removeTextbookFile(idx) {
    if (idx >= 0 && idx < textbookFiles.length) {
      const removed = textbookFiles.splice(idx, 1);
      renderTextbookFiles();
      if (removed.length > 0) {
        ui.showToast(`Removed textbook: ${removed[0].name}`, "info");
      }
    }
  }

  function renderTextbookFiles() {
    if (!textbookFileInfo) return;
    if (!textbookFiles || textbookFiles.length === 0) {
      textbookFileInfo.classList.add("hidden");
      if (textbookFileList) textbookFileList.innerHTML = "";
      if (textbookFileName) textbookFileName.textContent = "No file";
      return;
    }
    textbookFileInfo.classList.remove("hidden");
    if (textbookFileCount) {
      textbookFileCount.textContent = `Textbooks (${textbookFiles.length}):`;
    }
    if (textbookFileName) {
      textbookFileName.textContent = textbookFiles.map(f => f.name).join(", ");
    }
    if (textbookFileList) {
      textbookFileList.innerHTML = "";
      textbookFiles.forEach((f, idx) => {
        const chip = document.createElement("span");
        chip.style.cssText = "background:#f3e8ff; border:1px solid #d8b4fe; border-radius:4px; padding:0.15rem 0.4rem; display:inline-flex; align-items:center; gap:0.25rem; font-size:0.72rem; color:#6b21a8; max-width:220px;";
        
        const nameSpan = document.createElement("span");
        nameSpan.style.cssText = "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;";
        nameSpan.textContent = f.name;
        nameSpan.title = f.name;
        chip.appendChild(nameSpan);

        const rmBtn = document.createElement("button");
        rmBtn.type = "button";
        rmBtn.style.cssText = "background:none; border:none; color:#9333ea; font-size:0.75rem; cursor:pointer; font-weight:700; padding:0 0.15rem; line-height:1;";
        rmBtn.textContent = "✕";
        rmBtn.title = `Remove ${f.name}`;
        rmBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          removeTextbookFile(idx);
        });
        chip.appendChild(rmBtn);
        textbookFileList.appendChild(chip);
      });
    }
  }

  // Helper: update the live model/page status chips
  function updateModelStatusPanel(job) {
    if (!job) return;
    // Active model chip
    if (activeModelLabel) {
      const modelName = job.active_model || "";
      if (modelName) {
        const isFlash = modelName.toLowerCase().includes("flash");
        const isPro = modelName.toLowerCase().includes("pro");
        const icon = isPro ? "🧠" : "⚡";
        activeModelLabel.textContent = `${icon} ${modelName}`;
        const chip = document.getElementById("activeModelChip");
        if (chip) {
          chip.style.background = isPro ? "#fdf4ff" : "#eff6ff";
          chip.style.borderColor = isPro ? "#e9d5ff" : "#bfdbfe";
          chip.style.color = isPro ? "#7e22ce" : "#1d4ed8";
        }
      }
    }
    // Page chip
    if (pageStatusLabel && job.current_page != null && job.total_pages != null) {
      pageStatusLabel.textContent = `Page ${job.current_page}/${job.total_pages}`;
    }
    // Questions chip
    if (questionsFoundLabel) {
      const total = (job.results || []).reduce((s, r) => s + (r.total_questions || 0), 0);
      questionsFoundLabel.textContent = `${total} questions`;
    }
    // Model switch / quota warning banner
    if (modelSwitchBanner && job.warnings && job.warnings.length > 0) {
      const latestWarning = job.warnings[job.warnings.length - 1];
      if (latestWarning !== lastKnownModelStatus) {
        lastKnownModelStatus = latestWarning;
        modelSwitchBanner.textContent = latestWarning;
        modelSwitchBanner.classList.remove("hidden");
      }
    }
    // Partial download banner
    if (partialDownloadBanner) {
      const isPartial = job.status === "partial" || (job.results || []).some(r => r.is_partial);
      if (isPartial) {
        partialDownloadBanner.classList.remove("hidden");
      }
    }
  }



  function removeFile(index) {
    selectedFiles.splice(index, 1);
    ui.renderFileList(selectedFiles, removeFile, openFileOptions);
  }

  // 4. API Key Modal Handlers
  const openApiKeyModalBtn = document.getElementById("openApiKeyModalBtn");
  const closeApiKeyModalBtn = document.getElementById("closeApiKeyModalBtn");
  const cancelApiKeyBtn = document.getElementById("cancelApiKeyBtn");
  const saveApiKeyBtn = document.getElementById("saveApiKeyBtn");
  const apiKeyModal = document.getElementById("apiKeyModal");
  const apiKeyInput = document.getElementById("apiKeyInput");

  openApiKeyModalBtn.addEventListener("click", () => {
    apiKeyInput.value = apiKey;
    apiKeyModal.classList.remove("hidden");
  });

  [closeApiKeyModalBtn, cancelApiKeyBtn].forEach(btn => {
    btn.addEventListener("click", () => {
      apiKeyModal.classList.add("hidden");
    });
  });

  saveApiKeyBtn.addEventListener("click", () => {
    apiKey = apiKeyInput.value.trim();
    if (apiKey) {
      localStorage.setItem("gemini_api_key", apiKey);
    } else {
      localStorage.removeItem("gemini_api_key");
    }
    apiKeyModal.classList.add("hidden");
    checkBackendHealth();
    fetchQuotaStatus();
  });

  // 4B. Quota Modal Handlers
  const quotaPill = document.getElementById("quotaPill");
  const quotaModal = document.getElementById("quotaModal");
  const closeQuotaModalBtn = document.getElementById("closeQuotaModalBtn");
  const closeQuotaModalFooterBtn = document.getElementById("closeQuotaModalFooterBtn");
  const runQuotaTestBtn = document.getElementById("runQuotaTestBtn");
  const manageKeysFromQuotaBtn = document.getElementById("manageKeysFromQuotaBtn");

  if (quotaPill) {
    quotaPill.addEventListener("click", () => {
      fetchQuotaStatus();
      if (quotaModal) quotaModal.classList.remove("hidden");
    });
  }

  [closeQuotaModalBtn, closeQuotaModalFooterBtn].forEach(btn => {
    if (btn) {
      btn.addEventListener("click", () => {
        if (quotaModal) quotaModal.classList.add("hidden");
      });
    }
  });

  if (manageKeysFromQuotaBtn) {
    manageKeysFromQuotaBtn.addEventListener("click", () => {
      if (quotaModal) quotaModal.classList.add("hidden");
      apiKeyInput.value = apiKey;
      if (apiKeyModal) apiKeyModal.classList.remove("hidden");
    });
  }

  const resetQuotaCounterBtn = document.getElementById("resetQuotaCounterBtn");
  if (resetQuotaCounterBtn) {
    resetQuotaCounterBtn.addEventListener("click", async () => {
      try {
        const res = await fetch(`${API_BASE}/api/reset-quota`, { method: "POST" });
        const data = await res.json();
        ui.showToast("Quota counter reset: 0 used (100% available)", "success");
        fetchQuotaStatus();
      } catch (err) {
        ui.showToast(`Failed to reset: ${err.message}`, "error");
      }
    });
  }

  if (runQuotaTestBtn) {
    runQuotaTestBtn.addEventListener("click", async () => {
      ui.showQuotaTestLoading();
      try {
        const formData = new FormData();
        if (apiKey) formData.append("api_key", apiKey);
        const selModel = document.getElementById("modelSelector") ? document.getElementById("modelSelector").value : "gemini-3.5-flash";
        formData.append("model_name", selModel);

        const res = await fetch(`${API_BASE}/api/test-quota`, {
          method: "POST",
          body: formData
        });
        const data = await res.json();
        ui.showQuotaTestResult(data);
        fetchQuotaStatus();
      } catch (err) {
        ui.showQuotaTestResult({
          success: false,
          status: "network_error",
          message: `Network error while testing quota: ${err.message}`
        });
      }
    });
  }

  // 5. Raw JSON & File Export Modal Handlers
  const viewRawJsonBtn = document.getElementById("viewRawJsonBtn");
  const closeRawJsonModalBtn = document.getElementById("closeRawJsonModalBtn");
  const closeRawJsonFooterBtn = document.getElementById("closeRawJsonFooterBtn");
  const copyJsonBtn = document.getElementById("copyJsonBtn");
  const downloadJsonModalBtn = document.getElementById("downloadJsonModalBtn");
  const rawJsonModal = document.getElementById("rawJsonModal");

  // File Export Modal elements
  const openDownloadCenterBtn = document.getElementById("openDownloadCenterBtn");
  const fileExportModal = document.getElementById("fileExportModal");
  const closeFileExportModalBtn = document.getElementById("closeFileExportModalBtn");
  const closeFileExportFooterBtn = document.getElementById("closeFileExportFooterBtn");
  const modalDownloadExcelBtn = document.getElementById("modalDownloadExcelBtn");
  const modalDownloadCsvBtn = document.getElementById("modalDownloadCsvBtn");
  const modalDownloadPdfBtn = document.getElementById("modalDownloadPdfBtn");


  function openFileOptions(fileName = null) {
    if (batchResults.length === 0 && selectedFiles.length > 0) {
      alert("Please click 'Start Batch Extraction' first to extract questions before downloading.");
      return;
    }
    ui.showFileExportModal(fileName, batchResults, downloadSpecificFile);
  }

  openDownloadCenterBtn.addEventListener("click", () => {
    openFileOptions(null);
  });

  [closeFileExportModalBtn, closeFileExportFooterBtn].forEach(btn => {
    if (btn) {
      btn.addEventListener("click", () => {
        fileExportModal.classList.add("hidden");
      });
    }
  });

  modalDownloadExcelBtn.addEventListener("click", () => {
    if (ui.selectedTargetFile) {
      downloadSpecificFile("excel", ui.selectedTargetFile);
    } else {
      exportExcel();
    }
  });

  modalDownloadCsvBtn.addEventListener("click", () => {
    if (ui.selectedTargetFile) {
      downloadSpecificFile("csv", ui.selectedTargetFile);
    } else {
      exportCsv();
    }
  });

  if (modalDownloadPdfBtn) {
    modalDownloadPdfBtn.addEventListener("click", () => {
      if (ui.selectedTargetFile) {
        downloadSpecificFile("pdf", ui.selectedTargetFile);
      } else {
        exportPdf();
      }
    });
  }

  async function triggerFileDownload(url, defaultFilename) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) {
        window.location.href = url;
        return;
      }
      const blob = await resp.blob();
      let filename = defaultFilename;
      const disposition = resp.headers.get("Content-Disposition");
      if (disposition && disposition.includes("filename=")) {
        const match = disposition.match(/filename="?([^";]+)"?/);
        if (match && match[1]) filename = match[1];
      }
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        URL.revokeObjectURL(blobUrl);
        a.remove();
      }, 1500);
    } catch (e) {
      console.warn("Direct blob download error, falling back:", e);
      window.location.href = url;
    }
  }

  function downloadSpecificFile(format, fileName, category = null) {
    const effectiveJobId = currentJobId || "latest";
    const extMap = { excel: "xlsx", csv: "csv", json: "json", pdf: "pdf" };
    const ext = extMap[format] || format;
    const safeName = (fileName || "mcq").replace(/\.pdf$/i, "").replace(/_(?:mcqs?|export)$/i, "");

    const targetRes = batchResults.find(r => r.file_name === fileName || (r.file_name && r.file_name.endsWith(fileName)));
    const isAdvance = targetRes ? (targetRes.is_advance === true) : false;
    const marksParam = selectedMarks !== null ? `&marks=${selectedMarks}` : "";
    const marksQuery = selectedMarks !== null ? `?marks=${selectedMarks}` : "";

    if (format === "excel" && category) {
      triggerFileDownload(
        `${API_BASE}/api/export/${effectiveJobId}/file/${encodeURIComponent(fileName)}/excel?category=${category}${marksParam}`,
        `${safeName}_${category}.xlsx`
      );
      return;
    }

    if (format === "excel" && isAdvance) {
      // Deliver 3 separate individual single-sheet Excel files for JEE Advanced!
      triggerFileDownload(
        `${API_BASE}/api/export/${effectiveJobId}/file/${encodeURIComponent(fileName)}/excel?category=questions${marksParam}`,
        `${safeName}_Questions.xlsx`
      );
      setTimeout(() => {
        triggerFileDownload(
          `${API_BASE}/api/export/${effectiveJobId}/file/${encodeURIComponent(fileName)}/excel?category=paragraph${marksParam}`,
          `${safeName}_Paragraph_Type.xlsx`
        );
      }, 400);
      setTimeout(() => {
        triggerFileDownload(
          `${API_BASE}/api/export/${effectiveJobId}/file/${encodeURIComponent(fileName)}/excel?category=matching${marksParam}`,
          `${safeName}_Match_the_list.xlsx`
        );
      }, 800);
      return;
    }

    if (format === "excel" || format === "csv") {
      triggerFileDownload(
        `${API_BASE}/api/export/${effectiveJobId}/file/${encodeURIComponent(fileName)}/${format}${marksQuery}`,
        `${safeName}_mcqs.${ext}`
      );
    } else {
      triggerFileDownload(
        `${API_BASE}/api/export/${effectiveJobId}/file/${encodeURIComponent(fileName)}/${format}`,
        `${safeName}_mcqs.${ext}`
      );
    }
  }


  viewRawJsonBtn.addEventListener("click", () => {
    const allQuestions = [];
    batchResults.forEach(res => {
      res.questions.forEach(q => allQuestions.push(q));
    });
    ui.showRawJsonModal({ questions: allQuestions });
  });

  [closeRawJsonModalBtn, closeRawJsonFooterBtn].forEach(btn => {
    btn.addEventListener("click", () => {
      rawJsonModal.classList.add("hidden");
    });
  });

  copyJsonBtn.addEventListener("click", () => {
    const code = document.getElementById("rawJsonContent").textContent;
    navigator.clipboard.writeText(code).then(() => {
      copyJsonBtn.textContent = "Copied!";
      setTimeout(() => copyJsonBtn.textContent = "Copy JSON", 2000);
    });
  });

  downloadJsonModalBtn.addEventListener("click", () => {
    exportJson();
  });

  // Token Calculator Modal Events
  const closeTokenModalBtn = document.getElementById("closeTokenModalBtn");
  const closeTokenModalFooterBtn = document.getElementById("closeTokenModalFooterBtn");
  const tokenModal = document.getElementById("tokenModal");

  [closeTokenModalBtn, closeTokenModalFooterBtn].forEach(btn => {
    if (btn) {
      btn.addEventListener("click", () => {
        tokenModal.classList.add("hidden");
      });
    }
  });

  async function runTokenEstimation(filesList) {
    const filesWithBinary = (filesList || []).filter(f => f instanceof File);
    if (filesWithBinary.length === 0) {
      fileInput.click();
      return;
    }
    ui.openTokenLoadingModal();

    const selectedModel = (modelSelector && modelSelector.value) ? modelSelector.value : "gemini-3.1-flash-lite";
    const formData = new FormData();
    filesWithBinary.forEach(file => {
      formData.append("files", file);
    });
    formData.append("model_name", selectedModel);
    if (apiKey) {
      formData.append("api_key", apiKey);
    }

    try {
      const response = await fetch(`${API_BASE}/api/count-tokens`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Failed to calculate tokens.");
      }

      const report = await response.json();
      ui.showTokenReport(report);
    } catch (err) {
      ui.showTokenError(err.message);
    }
  }

  if (checkTokensBtn) {
    checkTokensBtn.addEventListener("click", async () => {
      if (selectedFiles.length === 0) {
        // Open file picker and calculate tokens upon selection
        const onTempFilePick = () => {
          if (fileInput.files && fileInput.files.length > 0) {
            const pickedFiles = Array.from(fileInput.files);
            handleFiles(pickedFiles);
            fileInput.removeEventListener("change", onTempFilePick);
            runTokenEstimation(pickedFiles);
          }
        };
        fileInput.addEventListener("change", onTempFilePick, { once: true });
        fileInput.click();
        return;
      }

      runTokenEstimation(selectedFiles);
    });
  }

  // 6. Extraction Execution
  const modelSelector = document.getElementById("modelSelector");

  if (modelSelector) {
    let savedModel = localStorage.getItem("preferred_gemini_model");
    const validModels = [
      "gemini-3.5-flash",
      "gemini-3.6-flash",
      "gemini-3.7-flash",
      "gemini-3.7-flash-lite",
      "gemini-3.5-flash-lite",
      "gemini-3.1-pro",
      "gemini-3.1-flash-lite",
      "gemini-2.5-flash",
      "gemini-2.5-pro",
      "gemini-2.0-flash",
      "gemini-2.0-flash-lite",
      "gemini-1.5-flash",
      "gemini-1.5-pro",
      "gemma-4-26b-a4b-it",
      "gemma-4-31b-it"
    ];
    if (!savedModel || !validModels.includes(savedModel)) {
      savedModel = "gemini-3.5-flash";
      localStorage.setItem("preferred_gemini_model", savedModel);
    }
    if ([...modelSelector.options].some(o => o.value === savedModel)) {
      modelSelector.value = savedModel;
    }
    modelSelector.addEventListener("change", () => {
      const selectedVal = modelSelector.value;
      localStorage.setItem("preferred_gemini_model", selectedVal);
      const optText = modelSelector.options[modelSelector.selectedIndex]?.text || selectedVal;
      ui.showToast(`Selected: ${optText}`, "info");
    });
  }

  startExtractionBtn.addEventListener("click", async () => {
    const filesWithBinary = selectedFiles.filter(f => f instanceof File);
    if (filesWithBinary.length === 0 && (!textbookFiles || textbookFiles.length === 0)) {
      // Guide user to select files if clicked without fresh binary files
      fileInput.click();
      return;
    }

    startExtractionBtn.disabled = true;
    if (modelSelector) modelSelector.disabled = true;

    // ── Immediately clear old results from UI so stale data is never shown ──
    batchResults = [];
    currentJobId = null;
    ui.updateStats([], downloadSpecificFile);   // Wipes question cards + stats
    ui.showProgress(true, "Uploading and initializing extraction pipeline...", 5, "Preparing requests...");

    const selectedModel = (modelSelector && modelSelector.value) ? modelSelector.value : "gemini-3.5-flash";

    const formData = new FormData();
    filesWithBinary.forEach(file => {
      formData.append("files", file);
    });
    // Append optional textbook PDF(s) if provided (Topic & Chapter Structure)
    if (textbookFiles && textbookFiles.length > 0) {
      textbookFiles.forEach(tbFile => {
        formData.append("textbook_pdf", tbFile);
      });
    }
    // Append optional solution PDF(s) if provided
    if (solutionFiles && solutionFiles.length > 0) {
      solutionFiles.forEach(solFile => {
        formData.append("solution_pdf", solFile);
      });
    }
    formData.append("model_name", selectedModel);
    if (apiKey) {
      formData.append("api_key", apiKey);
    }

    // Reset status panel
    lastKnownModelStatus = "";
    if (modelSwitchBanner) modelSwitchBanner.classList.add("hidden");
    if (partialDownloadBanner) partialDownloadBanner.classList.add("hidden");
    if (activeModelLabel) activeModelLabel.textContent = `⚡ ${selectedModel}`;
    if (pageStatusLabel) pageStatusLabel.textContent = "Page 0/0";
    if (questionsFoundLabel) questionsFoundLabel.textContent = "0 questions";


    try {
      const response = await fetch(`${API_BASE}/api/batch-extract`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Batch extraction failed to start.");
      }

      const jobData = await response.json();
      currentJobId = jobData.job_id;
      startJobPolling(currentJobId, filesWithBinary.length);

    } catch (error) {
      ui.showProgress(false);
      startExtractionBtn.disabled = false;
      if (modelSelector) modelSelector.disabled = false;
      alert(`Error starting extraction: ${error.message}`);
    }
  });

  // 7. Polling for Job Completion
  function startJobPolling(jobId, totalFiles) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
        if (res.status === 404) {
          console.warn(`Job ${jobId} not found on backend. Stopping poll.`);
          clearInterval(pollInterval);
          startExtractionBtn.disabled = false;
          if (modelSelector) modelSelector.disabled = false;
          ui.showProgress(false);
          return;
        }
        if (!res.ok) return;

        const job = await res.json();

        // Update live model/page status chips
        updateModelStatusPanel(job);

        // Calculate fine-grained page-level percentage
        let pageFraction = 0;
        if (job.total_pages && job.total_pages > 0 && job.current_page) {
          pageFraction = Math.min(0.95, job.current_page / job.total_pages);
        }
        let rawPercent = ((job.processed_files + pageFraction) / Math.max(1, totalFiles)) * 100;

        // If in solution extraction / mapping phase, smoothly scale between 90% and 98%
        if (job.progress_message && job.progress_message.toLowerCase().includes("extracting solutions")) {
          const solPageMatch = job.progress_message.match(/Page\s+(\d+)\/(\d+)/i);
          if (solPageMatch) {
            const curP = parseInt(solPageMatch[1], 10);
            const totP = Math.max(1, parseInt(solPageMatch[2], 10));
            rawPercent = 90 + Math.round((curP / totP) * 8);
          } else {
            rawPercent = 92;
          }
        }

        const percent = Math.min(98, Math.max(8, Math.round(rawPercent)));

        // Progress text: show model_status from backend if available
        const modelStatusText = job.model_status || (modelSelector.options[modelSelector.selectedIndex]?.text || "Gemini AI");
        const progressTitle = job.progress_message || `Scanning with ${modelStatusText}...`;

        let detailsParts = [];
        if (job.current_file) {
          detailsParts.push(`📄 ${job.current_file}`);
        }
        if (job.extracted_questions_count !== undefined && job.extracted_questions_count > 0) {
          detailsParts.push(`💡 ${job.extracted_questions_count} question(s) found`);
        } else if (job.results && job.results.length > 0) {
          const totalFound = job.results.reduce((sum, r) => sum + (r.total_questions || 0), 0);
          detailsParts.push(`💡 ${totalFound} question(s) found`);
        }
        if (job.active_model) {
          detailsParts.push(`🤖 ${job.active_model}`);
        }
        detailsParts.push(`File ${Math.min(totalFiles, job.processed_files + (job.status === 'processing' ? 1 : 0))}/${totalFiles}`);

        ui.showProgress(
          true,
          progressTitle,
          percent,
          detailsParts.join(" • ")
        );

        if (job.results && job.results.length > 0) {
          batchResults = job.results;
          ui.updateStats(batchResults, downloadSpecificFile);
        }

        if (job.status === "completed" || job.status === "failed" || job.status === "partial") {
          clearInterval(pollInterval);
          startExtractionBtn.disabled = false;
          if (modelSelector) modelSelector.disabled = false;
          fetchQuotaStatus();

          if (job.status === "completed") {
            const totalExtracted = (job.results || []).reduce((sum, r) => sum + (r.total_questions || 0), 0);
            const totalPages = (job.results || []).reduce((sum, r) => sum + (r.total_pages_scanned || 0), 0);
            const activeModelUsed = job.active_model || (job.results || []).find(r => r.model_used)?.model_used || selectedModel;

            ui.showProgress(
              true,
              "Extraction Complete! 🎉",
              100,
              `Scanned ${totalPages} page(s) • ${totalExtracted} questions extracted • Model: ${activeModelUsed}`
            );
            if (job.results && job.results.length > 0) {
              batchResults = job.results;
              ui.updateStats(batchResults, downloadSpecificFile);
            }
            setTimeout(() => {
              ui.showProgress(false);
              ui.showToast(`🎉 Extraction Complete! ${totalExtracted} questions extracted.`, "success");
            }, 1200);

          } else if (job.status === "partial") {
            // Both models exhausted mid-scan — partial output preserved
            const totalExtracted = (job.results || []).reduce((sum, r) => sum + (r.total_questions || 0), 0);
            if (job.results && job.results.length > 0) {
              batchResults = job.results;
              ui.updateStats(batchResults, downloadSpecificFile);
            }
            updateModelStatusPanel(job);   // Show the partial banner
            ui.showProgress(
              true,
              "⛔ Stopped — Both Models Exhausted",
              Math.round((job.processed_files / Math.max(1, totalFiles)) * 100),
              `${totalExtracted} questions extracted and ready for download`
            );
            ui.showToast(
              `⛔ Both Gemini models hit their quota limit. ${totalExtracted} questions preserved — download now!`,
              "warning"
            );

          } else {
            // Failed
            ui.showProgress(false);
            if (job.results && job.results.length > 0) {
              batchResults = job.results;
              ui.updateStats(batchResults, downloadSpecificFile);
            }
            const err = job.error || job.progress_message || 'Unknown error';
            ui.showToast(`Extraction Notice: ${err}`, "warning");
            if (err.includes('API Key') || err.includes('401') || err.includes('403')) {
              const apiKeyBtn = document.getElementById('openApiKeyModalBtn');
              if (apiKeyBtn) apiKeyBtn.click();
            }
          }
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1500);
  }

  // 8. Filters & Search Handlers
  document.getElementById("searchInput").addEventListener("input", () => {
    ui.renderQuestionsStream();
  });

  document.getElementById("imageFilterSelect").addEventListener("change", () => {
    ui.renderQuestionsStream();
  });

  // ── Marks Parameter Controller (1 Mark / 4 Marks / Auto) ───────────────────
  let selectedMarks = 4; // Default 4 Marks

  function setMarksParameter(val) {
    if (val === "auto" || val === "custom" || val === null) {
      selectedMarks = null;
    } else {
      selectedMarks = parseInt(val, 10) || 4;
    }

    // Update active class on toolbar pills
    document.querySelectorAll("#marksPillGroup .btn-marks-pill").forEach(btn => {
      const bMarks = btn.getAttribute("data-marks");
      if ((selectedMarks === null && bMarks === "auto") || (selectedMarks !== null && bMarks === String(selectedMarks))) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // Update active class on modal pills
    document.querySelectorAll("#modalMarksPillGroup .btn-marks-pill").forEach(btn => {
      const bMarks = btn.getAttribute("data-marks");
      if ((selectedMarks === null && bMarks === "auto") || (selectedMarks !== null && bMarks === String(selectedMarks))) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // Update questions in memory if explicit marks selected
    if (selectedMarks !== null && batchResults && batchResults.length > 0) {
      batchResults.forEach(res => {
        (res.questions || []).forEach(q => {
          q.marks = selectedMarks;
        });
      });
      ui.renderQuestionsStream();
      ui.showToast(`🎯 Marks set to ${selectedMarks} Mark${selectedMarks === 4 ? 's' : ''} for Excel Export`, "info");
    } else if (selectedMarks === null && batchResults && batchResults.length > 0) {
      ui.renderQuestionsStream();
      ui.showToast(`🎯 Marks set to Auto (Preserve individual question marks)`, "info");
    }
  }

  // Attach listeners to toolbar marks pills
  document.querySelectorAll("#marksPillGroup .btn-marks-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      setMarksParameter(btn.getAttribute("data-marks"));
    });
  });

  // Attach listeners to modal marks pills
  document.querySelectorAll("#modalMarksPillGroup .btn-marks-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      setMarksParameter(btn.getAttribute("data-marks"));
    });
  });

  // 9. Exports
  function exportJson() {
    const effectiveJobId = currentJobId || "latest";
    triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/json`, `mcq_export_${Date.now()}.json`);
  }

  function exportCsv() {
    const effectiveJobId = currentJobId || "latest";
    const marksQuery = selectedMarks !== null ? `?marks=${selectedMarks}` : "";
    triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/csv${marksQuery}`, `mcq_export_${Date.now()}.csv`);
  }

  function exportExcel(category = null) {
    const effectiveJobId = currentJobId || "latest";
    const isAdvance = batchResults.some(r => r.is_advance === true);
    const marksParam = selectedMarks !== null ? `&marks=${selectedMarks}` : "";
    const marksQuery = selectedMarks !== null ? `?marks=${selectedMarks}` : "";

    if (category) {
      triggerFileDownload(
        `${API_BASE}/api/export/${effectiveJobId}/excel?category=${category}${marksParam}`,
        `mcq_export_${category}_${Date.now()}.xlsx`
      );
      return;
    }

    if (isAdvance) {
      // Deliver 3 separate individual single-sheet Excel files for JEE Advanced!
      triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/excel?category=questions${marksParam}`, `mcq_export_Questions_${Date.now()}.xlsx`);
      setTimeout(() => {
        triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/excel?category=paragraph${marksParam}`, `mcq_export_Paragraph_Type_${Date.now()}.xlsx`);
      }, 400);
      setTimeout(() => {
        triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/excel?category=matching${marksParam}`, `mcq_export_Match_the_list_${Date.now()}.xlsx`);
      }, 800);
    } else {
      triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/excel${marksQuery}`, `mcq_export_${Date.now()}.xlsx`);
    }
  }

  function exportPdf() {
    const effectiveJobId = currentJobId || "latest";
    triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/pdf`, `mcq_export_${Date.now()}.pdf`);
  }

  function exportImages() {
    const effectiveJobId = currentJobId || "latest";
    triggerFileDownload(`${API_BASE}/api/export/${effectiveJobId}/images`, `diagrams_${Date.now()}.zip`);
  }

  document.getElementById("exportCsvBtn").addEventListener("click", exportCsv);
  document.getElementById("exportExcelBtn").addEventListener("click", exportExcel);
  const exportPdfBtn = document.getElementById("exportPdfBtn");
  if (exportPdfBtn) exportPdfBtn.addEventListener("click", exportPdf);
  const exportImagesBtn = document.getElementById("exportImagesBtn");
  if (exportImagesBtn) exportImagesBtn.addEventListener("click", exportImages);

  // Partial download (shown when both models exhaust mid-scan)
  if (partialDownloadExcelBtn) {
    partialDownloadExcelBtn.addEventListener("click", exportExcel);
  }

  // 10. Clear Workspace / New Scan Handlers
  function clearWorkspace() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    selectedFiles = [];
    textbookFiles = [];
    solutionFiles = [];
    batchResults = [];
    currentJobId = null;
    lastKnownModelStatus = "";
    localStorage.removeItem("last_selected_files");
    localStorage.removeItem("last_job_id");
    fileInput.value = "";
    // Reset textbook PDF UI
    if (textbookFileInput) textbookFileInput.value = "";
    renderTextbookFiles();
    // Reset solution PDF UI
    if (solutionFileInput) solutionFileInput.value = "";
    renderSolutionFiles();
    // Reset model status panel
    if (modelSwitchBanner) modelSwitchBanner.classList.add("hidden");
    if (partialDownloadBanner) partialDownloadBanner.classList.add("hidden");
    if (activeModelLabel) activeModelLabel.textContent = "Flash";
    if (pageStatusLabel) pageStatusLabel.textContent = "Page 0/0";
    if (questionsFoundLabel) questionsFoundLabel.textContent = "0 questions";
    ui.renderFileList([], removeFile, openFileOptions);
    ui.updateStats([]);
    ui.showProgress(false);
    startExtractionBtn.disabled = false;
    if (checkTokensBtn) checkTokensBtn.disabled = false;
  }

  const clearWorkspaceBtn = document.getElementById("clearWorkspaceBtn");
  if (clearWorkspaceBtn) {
    clearWorkspaceBtn.addEventListener("click", clearWorkspace);
  }

  const clearResultsBtn = document.getElementById("clearResultsBtn");
  if (clearResultsBtn) {
    clearResultsBtn.addEventListener("click", clearWorkspace);
  }

  // ── 11. Live Logs Controller ───────────────────────────────────────────────
  let logsPollInterval = null;
  let cachedLogsData = null;

  async function fetchLogs() {
    try {
      const res = await fetch(`${API_BASE}/api/logs?limit=300`);
      if (res.ok) {
        cachedLogsData = await res.json();
        const searchVal = ui.logsSearchInput ? ui.logsSearchInput.value : "";
        ui.renderLogs(cachedLogsData, searchVal, ui.activeLogLevelFilter);
      }
    } catch (err) {
      console.warn("Failed to fetch logs:", err);
    }
  }

  function startLogsPolling() {
    fetchLogs();
    if (!logsPollInterval) {
      logsPollInterval = setInterval(() => {
        if (ui.logsAutoRefreshCheck && ui.logsAutoRefreshCheck.checked) {
          fetchLogs();
        }
      }, 1500);
    }
  }

  function stopLogsPolling() {
    if (logsPollInterval) {
      clearInterval(logsPollInterval);
      logsPollInterval = null;
    }
  }

  // Open / Close modal buttons
  if (ui.openLiveLogsBtn) {
    ui.openLiveLogsBtn.addEventListener("click", () => {
      ui.showLiveLogsModal();
      startLogsPolling();
    });
  }

  if (ui.progressViewLogsBtn) {
    ui.progressViewLogsBtn.addEventListener("click", () => {
      ui.showLiveLogsModal();
      startLogsPolling();
    });
  }

  if (ui.closeLiveLogsModalBtn) {
    ui.closeLiveLogsModalBtn.addEventListener("click", () => {
      ui.hideLiveLogsModal();
      stopLogsPolling();
    });
  }

  if (ui.closeLiveLogsFooterBtn) {
    ui.closeLiveLogsFooterBtn.addEventListener("click", () => {
      ui.hideLiveLogsModal();
      stopLogsPolling();
    });
  }

  // Close modal when clicking on backdrop
  if (ui.liveLogsModal) {
    ui.liveLogsModal.addEventListener("click", (e) => {
      if (e.target === ui.liveLogsModal) {
        ui.hideLiveLogsModal();
        stopLogsPolling();
      }
    });
  }

  // Level filter pill buttons
  const filterPills = document.querySelectorAll("#logsLevelFilters .btn-filter-pill");
  filterPills.forEach(pill => {
    pill.addEventListener("click", () => {
      filterPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      ui.activeLogLevelFilter = pill.getAttribute("data-level") || "ALL";
      const searchVal = ui.logsSearchInput ? ui.logsSearchInput.value : "";
      if (cachedLogsData) {
        ui.renderLogs(cachedLogsData, searchVal, ui.activeLogLevelFilter);
      } else {
        fetchLogs();
      }
    });
  });

  // Search input typing
  if (ui.logsSearchInput) {
    ui.logsSearchInput.addEventListener("input", (e) => {
      const searchVal = e.target.value;
      if (cachedLogsData) {
        ui.renderLogs(cachedLogsData, searchVal, ui.activeLogLevelFilter);
      }
    });
  }

  // Clear logs button
  if (ui.clearLogsBtn) {
    ui.clearLogsBtn.addEventListener("click", async () => {
      if (!confirm("Are you sure you want to clear the logs?")) return;
      try {
        const res = await fetch(`${API_BASE}/api/logs`, { method: "DELETE" });
        if (res.ok) {
          cachedLogsData = { total: 0, logs: [], log_file_size_bytes: 0 };
          ui.renderLogs(cachedLogsData, "", ui.activeLogLevelFilter);
        }
      } catch (err) {
        console.error("Failed to clear logs:", err);
      }
    });
  }

  // Download logs button
  if (ui.downloadLogsBtn) {
    ui.downloadLogsBtn.addEventListener("click", () => {
      triggerFileDownload(`${API_BASE}/api/logs/download`, `mcq_app_${Date.now()}.log`);
    });
  }
});


