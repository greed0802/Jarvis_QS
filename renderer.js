(async function () {
  // Prevent double-init
  if (window._jarvisInitialized) return;
  window._jarvisInitialized = true;

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ==========================================================
  // SECTION 1: Sidebar View Switching (Activity Bar)
  // ==========================================================
  function showSection(id) {
    $$(".sidebar-section").forEach((el) => (el.hidden = true));
    const target = $("#section-" + id);
    if (target) target.hidden = false;
    const header = $(".sidebar-header .sidebar-title");
    if (header) header.textContent = id.charAt(0).toUpperCase() + id.slice(1);
  }

  $$(".activity-item[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".activity-item[data-view]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      showSection(btn.dataset.view);
    });
  });

  // ==========================================================
  // SECTION 2: Right AI Panel Tab Switching
  // ==========================================================
  $$(".panel-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".panel-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      $$(".panel-section").forEach((p) => {
        p.classList.remove("active");
        p.hidden = true;
      });
      const target = $("#panel-" + tab.dataset.panel);
      if (target) {
        target.classList.add("active");
        target.hidden = false;
      }
    });
  });

  // ==========================================================
  // SECTION 3: Window Controls (IPC -> Main Process)
  // ==========================================================
  const winMin = $("#winMinBtn");
  const winMax = $("#winMaxBtn");
  const winClose = $("#winCloseBtn");
  if (winMin) winMin.addEventListener("click", () => window.electronAPI.minimize());
  if (winMax) winMax.addEventListener("click", () => window.electronAPI.maximize());
  if (winClose) winClose.addEventListener("click", () => window.electronAPI.close());

  // ==========================================================
  // SECTION 4: AI Panel Toggle (Robot icon at bottom of Activity Bar)
  // ==========================================================
  let aiPanelOpen = true;
  const aiToggleBtn = $("#aiToggleBtn");
  const rightPanel = $("#rightPanel");

  if (aiToggleBtn && rightPanel) {
    aiToggleBtn.addEventListener("click", () => {
      aiPanelOpen = !aiPanelOpen;
      if (aiPanelOpen) {
        rightPanel.classList.remove("collapsed");
      } else {
        rightPanel.classList.add("collapsed");
      }
    });
  }

  // ==========================================================
  // SECTION 5: Chat - Live AI Brain via IPC
  // ==========================================================
  function formatAIResponse(rawText) {
    // Check if the response contains the typical thought process signature
    const thoughtRegex = /\*Thought Process:\s*\*(.*?)(?=\n\n|\n-|\n[A-Z]|$)/is;
    const match = rawText.match(thoughtRegex);

    if (match) {
      const thoughtContent = match[1].trim();
      // Remove the raw thought process from the main text
      const cleanedText = rawText.replace(match[0], '').trim();

      // Build the HTML accordion
      const detailsHtml = `
<details class="thought-process">
    <summary>View internal reasoning</summary>
    <p>${thoughtContent}</p>
</details>
`;
      return detailsHtml + "\n\n" + cleanedText;
    }

    return rawText;
  }

  function appendMessage(role, text, extraClass) {
    const container = $("#chatContainer");
    if (!container) return null;

    const wrap = document.createElement("div");
    wrap.className = "chat-message " + (role === "user" ? "user" : "assistant") + (extraClass ? " " + extraClass : "");

    const avatar = document.createElement("div");
    avatar.className = "chat-avatar";
    avatar.textContent = role === "user" ? "U" : "J";

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble message-bubble " + (role === "user" ? "user-message" : "ai-message");
    
    let processedText = text;
    if (role === "assistant" && extraClass !== "thinking") {
      processedText = formatAIResponse(text);
      if (processedText.includes("<details")) {
        bubble.innerHTML = processedText;
      } else {
        bubble.textContent = processedText;
      }
    } else {
      bubble.textContent = processedText;
    }

    wrap.appendChild(avatar);
    wrap.appendChild(bubble);
    container.appendChild(wrap);

    container.scrollTop = container.scrollHeight;
    return { wrap, bubble };
  }

  // ==========================================
  // 1. AUTO-SCROLL PINNING HELPERS
  // ==========================================
  const getChatContainer = () => document.querySelector('#chatContainer') || document.querySelector('.chat-messages') || document.querySelector('.chat-scroll-area');

  const isScrolledToBottom = () => {
    const el = getChatContainer();
    if (!el) return true;
    return (el.scrollHeight - el.clientHeight <= el.scrollTop + 50);
  };

  const scrollToBottom = () => {
    const el = getChatContainer();
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  };

  // ==========================================
  // 2. PANEL RESIZER INITIALIZATION
  // ==========================================
  function initPanelResizers() {
    const leftResizer = document.getElementById("resizer-left");
    const rightResizer = document.getElementById("resizer-right");
    const sidebar = document.querySelector(".sidebar-column") || document.getElementById("sidebar-container") || document.querySelector(".sidebar");
    const aiPanel = document.querySelector(".ai-panel-column") || document.getElementById("ai-panel-container") || document.getElementById("rightPanel");

    function makeResizable(resizer, targetPanel, isRightSide = false) {
        if (!resizer || !targetPanel) return;
        let startX, startWidth;

        resizer.addEventListener("pointerdown", (e) => {
            resizer.setPointerCapture(e.pointerId);
            startX = e.clientX;
            startWidth = parseInt(document.defaultView.getComputedStyle(targetPanel).width, 10);
            resizer.classList.add("resizing");
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";

            function onPointerMove(e) {
                let newWidth = isRightSide ? startWidth - (e.clientX - startX) : startWidth + (e.clientX - startX);
                const min = isRightSide ? 280 : 180;
                const max = isRightSide ? 800 : 500;
                if (newWidth > min && newWidth < max) {
                    targetPanel.style.width = `${newWidth}px`;
                }
            }

            function onPointerUp(e) {
                resizer.releasePointerCapture(e.pointerId);
                resizer.classList.remove("resizing");
                document.body.style.cursor = "";
                document.body.style.userSelect = "";
                resizer.removeEventListener("pointermove", onPointerMove);
                resizer.removeEventListener("pointerup", onPointerUp);
            }

            resizer.addEventListener("pointermove", onPointerMove);
            resizer.addEventListener("pointerup", onPointerUp);
        });
    }

    makeResizable(leftResizer, sidebar, false);
    makeResizable(rightResizer, aiPanel, true);
  }

  document.addEventListener("DOMContentLoaded", initPanelResizers);
  if (document.readyState === "complete" || document.readyState === "interactive") {
    initPanelResizers();
  }

  // ==========================================
  // 3. STREAMING EVENT LISTENERS & UI INJECTION
  // ==========================================

  // Track current active message bubble elements during a stream
  let activeAiBubble = null;
  let activeStepCard = null;
  let activeStepBody = null;
  let activeAnswerContent = null;
  let stepCounter = 0;

  function initializeStreamingBubble() {
    stepCounter = 0;
    const wasPinned = isScrolledToBottom();

    // Create assistant bubble container using the existing helper
    const aiMessage = appendMessage("assistant", "");
    if (!aiMessage) return;

    activeAiBubble = aiMessage.bubble;
    activeAiBubble.classList.add("ai-message", "message-bubble"); 
    activeAiBubble.innerHTML = ""; // Clear initial empty text

    // Create Flat Text Thinking Accordion Card
    activeStepCard = document.createElement('div');
    activeStepCard.className = 'agent-step-card expanded';

    const header = document.createElement('div');
    header.className = 'agent-step-header';
    header.innerHTML = `
        <svg class="step-chevron" viewBox="0 0 24 24" width="9" height="9" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
        <span class="thinking-dot"></span>
        <span class="step-title">Thinking...</span>
    `;

    // Bulletproof event listener using .closest() to target the exact card
    header.addEventListener('click', function() {
      const card = this.closest('.agent-step-card');
      if (card) {
        card.classList.toggle('expanded');
      }
    });

    activeStepBody = document.createElement('div');
    activeStepBody.className = 'agent-step-body';

    activeStepCard.appendChild(header);
    activeStepCard.appendChild(activeStepBody);
    activeAiBubble.appendChild(activeStepCard);

    // Create container for the final streamed answer text
    activeAnswerContent = document.createElement('div');
    activeAnswerContent.className = 'markdown-body answer-text';
    activeAnswerContent.style.whiteSpace = 'pre-wrap';
    activeAiBubble.appendChild(activeAnswerContent);

    if (wasPinned) scrollToBottom();
  }

  async function handleSend(e) {
    if (e) e.preventDefault();

    const inputEl = $("#chatInput");
    const sendBtn = $("#chatSend");
    if (!inputEl) return;

    const text = inputEl.value.trim();
    if (!text) return;

    appendMessage("user", text);
    inputEl.value = "";

    inputEl.disabled = true;
    if (sendBtn) sendBtn.disabled = true;

    // Reset stream active pointers for new prompt trigger
    activeAiBubble = null;
    activeStepCard = null;
    activeStepBody = null;
    activeAnswerContent = null;

    // INSTANTLY create the AI "Thinking..." block so there is zero lag time
    initializeStreamingBubble();

    try {
      await window.electronAPI.askJarvisStream(text);
    } catch (err) {
      console.error("[Stream trigger error]", err);
      if (activeAiBubble) {
        const wrapEl = activeAiBubble.closest('.chat-message');
        if (wrapEl) {
          wrapEl.remove();
        } else {
          activeAiBubble.remove();
        }
        activeAiBubble = null;
      }
      inputEl.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  // Handle incoming stream events from Electron IPC
  if (window.electronAPI && window.electronAPI.onJarvisStreamEvent) {
    window.electronAPI.onJarvisStreamEvent((event) => {
      if (!activeAiBubble) {
        initializeStreamingBubble();
      }

      const wasPinned = isScrolledToBottom();

      if (event.type === 'thought' || event.type === 'tool_start' || event.type === 'tool_end') {
        stepCounter++;
        if (activeStepBody) {
          const line = document.createElement('div');
          if (event.type === 'thought') {
            line.textContent = `› ${event.content}`;
          } else if (event.type === 'tool_start') {
            line.textContent = `› Running ${event.name} with input: ${event.input}`;
          } else {
            line.textContent = `› Completed ${event.name} - ${event.summary}`;
          }
          activeStepBody.appendChild(line);
          activeStepBody.scrollTop = activeStepBody.scrollHeight;
        }
      } else if (event.type === 'final_chunk') {
        if (activeAnswerContent) {
          activeAnswerContent.textContent += event.content;
        }
      }

      if (wasPinned) scrollToBottom();
    });
  }

  // Handle stream completion
  if (window.electronAPI && window.electronAPI.onJarvisStreamDone) {
    window.electronAPI.onJarvisStreamDone((result) => {
      if (!activeAiBubble) return;

      const inputField = document.getElementById("chatInput");
      const sendButton = document.getElementById("chatSend");

      // Grab the raw response text
      let fullText = activeAnswerContent ? activeAnswerContent.innerText : activeAiBubble.innerText;

      // Parse out the AI suggestions using a regex
      let dynamicChips = ["Summarize this", "Show source files", "Extract pricing data"]; // fallback
      const suggestionRegex = /\[SUGGESTIONS:\s*(.*?)\]/i;
      const match = fullText.match(suggestionRegex);

      if (match && match[1]) {
        // Split the captured string by pipe '|'
        dynamicChips = match[1].split('|').map(s => s.trim()).filter(Boolean);
        // Clean the tag out of the final displayed answer text
        fullText = fullText.replace(match[0], '').trim();
        if (activeAnswerContent) {
          activeAnswerContent.innerText = fullText;
        }
      }

      // 1. Update Thinking Header to Completed State
      const activeHeader = activeStepCard ? activeStepCard.querySelector('.agent-step-header') : null;
      if (activeHeader) {
        activeHeader.innerHTML = `
            <svg class="step-chevron" viewBox="0 0 24 24" width="9" height="9" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
            <span class="step-title">Thought process</span>
            <span class="step-status-text">(${stepCounter} steps)</span>
        `;
      }

      // Convert body layout to collapsed by default
      if (activeStepCard) activeStepCard.classList.remove("expanded");

      // 2. Inject Copy Button Action Bar
      const actionsContainer = document.createElement('div');
      actionsContainer.className = 'response-actions';

      const copyBtn = document.createElement('button');
      copyBtn.className = 'copy-btn';
      copyBtn.innerHTML = `<svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" fill="none" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> Copy`;

      copyBtn.onclick = () => {
        navigator.clipboard.writeText(fullText).then(() => {
          copyBtn.classList.add('copied');
          copyBtn.innerHTML = `<svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" fill="none" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg> Copied`;
          setTimeout(() => {
            copyBtn.classList.remove('copied');
            copyBtn.innerHTML = `<svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" fill="none" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> Copy`;
          }, 2000);
        });
      };
      actionsContainer.appendChild(copyBtn);
      activeAiBubble.appendChild(actionsContainer);

      // 3. Render the AI-Generated Suggestion Chips
      const suggestionsBox = document.createElement('div');
      suggestionsBox.className = 'suggestion-chips';

      dynamicChips.forEach(pText => {
        const chip = document.createElement('button');
        chip.className = 'suggestion-chip';
        chip.textContent = pText;
        chip.onclick = () => {
          const inputField = document.querySelector('.chat-input') || document.getElementById('chatInput');
          const sendBtn = document.querySelector('.send-btn') || document.getElementById('chatSend') || document.querySelector('.chat-send');
          if (inputField) inputField.value = pText;
          if (sendBtn) sendBtn.click();
        };
        suggestionsBox.appendChild(chip);
      });
      activeAiBubble.appendChild(suggestionsBox);

      // Re-enable typing inputs
      if (inputField) inputField.disabled = false;
      if (sendButton) sendButton.disabled = false;
      if (inputField) inputField.focus();

      // Reset active tracking pointers for next query
      activeAiBubble = null;
      activeStepCard = null;
      activeStepBody = null;
      activeAnswerContent = null;

      scrollToBottom();
    });
  }

  const sendBtn = $("#chatSend");
  if (sendBtn) {
    sendBtn.addEventListener("click", handleSend);
  }

  const chatInput = $("#chatInput");
  if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend(e);
      }
    });
  }

  // ==========================================================
  // SECTION 6: Settings - Native Node.js Configuration & Model Management
  // ==========================================================
  const PROVIDER_PRESETS = {
    omniroute: {
      base_url: "http://omni.dhanrickeviota.com/v1",
      api_key: "sk-9e731d7385077d7e-2cbf0c-598b3170",
      ollama_base_url: "http://localhost:11434/v1",
    },
    openai: {
      base_url: "https://api.openai.com/v1",
      api_key: "",
      ollama_base_url: "http://localhost:11434/v1",
    },
    anthropic: {
      base_url: "https://api.anthropic.com/v1",
      api_key: "",
      ollama_base_url: "http://localhost:11434/v1",
    },
    ollama: {
      base_url: "http://localhost:11434/v1",
      api_key: "ollama",
      ollama_base_url: "http://localhost:11434/v1",
    },
    custom: {
      base_url: "",
      api_key: "",
      ollama_base_url: "http://localhost:11434/v1",
    },
  };

  function setStatusMsg(msg, type) {
    const el = $("#settingsStatus");
    if (!el) return;
    el.textContent = msg;
    el.className = "settings-status" + (type ? " " + type : "");
  }

  function populateModelDropdown(selectId, models, selectedValue) {
    const sel = $("#" + selectId);
    if (!sel) return;
    sel.innerHTML = "";
    
    if (!models || models.length === 0) {
      const opt = document.createElement("option");
      opt.value = selectedValue || "default";
      opt.textContent = selectedValue || "No models found";
      sel.appendChild(opt);
      return;
    }

    // Ensure selectedValue is in options list
    let list = [...models];
    if (selectedValue && !list.includes(selectedValue)) {
      list.unshift(selectedValue);
    }

    list.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      if (m === selectedValue) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  async function loadConfig() {
    try {
      const cfg = await window.electronAPI.getConfig();
      if (!cfg) return;
      if ($("#baseUrl")) $("#baseUrl").value = cfg.base_url || "";
      if ($("#apiKey")) $("#apiKey").value = cfg.api_key || "";
      if ($("#ollamaBaseUrl")) $("#ollamaBaseUrl").value = cfg.ollama_base_url || "";
      if ($("#embeddingModel")) $("#embeddingModel").value = cfg.embedding_model || "";
      if ($("#config-inbox-path")) $("#config-inbox-path").value = cfg.inbox_path || "D:/knowledge_inbox";
      if ($("#config-faiss-path")) $("#config-faiss-path").value = cfg.faiss_path || "D:/Jarvis_QS/faiss_data";
      if ($("#providerType") && cfg.provider_type) {
        $("#providerType").value = cfg.provider_type;
      }
      const primaryVal = cfg.primary_model || "jarvis_brain";
      const fallbackVal = cfg.fallback_model || "qwen2.5-coder:3b-instruct-q4_K_M";
      populateModelDropdown("primaryModel", [primaryVal], primaryVal);
      populateModelDropdown("fallbackModel", [fallbackVal], fallbackVal);
    } catch (e) {
      console.warn("Config load failed:", e);
    }
  }

  // Provider preset auto-fill
  const providerSelect = $("#providerType");
  if (providerSelect) {
    providerSelect.addEventListener("change", () => {
      const preset = PROVIDER_PRESETS[providerSelect.value];
      if (!preset) return;
      if ($("#baseUrl")) $("#baseUrl").value = preset.base_url;
      if ($("#apiKey") && preset.api_key !== undefined) $("#apiKey").value = preset.api_key;
      if ($("#ollamaBaseUrl")) $("#ollamaBaseUrl").value = preset.ollama_base_url;
    });
  }

  // Sync / Auto-Fetch Models Button
  const syncBtn = $("#syncModelsBtn");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      const baseUrl = $("#baseUrl") ? $("#baseUrl").value.trim() : "";
      const apiKey = $("#apiKey") ? $("#apiKey").value.trim() : "";
      const ollamaUrl = $("#ollamaBaseUrl") ? $("#ollamaBaseUrl").value.trim() : "";

      if (!baseUrl) {
        setStatusMsg("Enter a base URL first.", "error");
        return;
      }

      syncBtn.disabled = true;
      const originalText = syncBtn.innerHTML;
      syncBtn.textContent = "Fetching...";
      setStatusMsg("");

      try {
        // Fetch Primary endpoint models
        const primaryResult = await window.electronAPI.fetchModels(baseUrl, apiKey);
        const curPrimary = $("#primaryModel") ? $("#primaryModel").value : "";
        
        if (primaryResult && primaryResult.success && primaryResult.models.length > 0) {
          populateModelDropdown("primaryModel", primaryResult.models, curPrimary || primaryResult.models[0]);
        }

        // Fetch Fallback (Ollama) endpoint models
        const fallbackTarget = ollamaUrl || "http://localhost:11434/v1";
        const fallbackResult = await window.electronAPI.fetchModels(fallbackTarget, apiKey);
        const curFallback = $("#fallbackModel") ? $("#fallbackModel").value : "";

        if (fallbackResult && fallbackResult.success && fallbackResult.models.length > 0) {
          populateModelDropdown("fallbackModel", fallbackResult.models, curFallback || fallbackResult.models[0]);
        } else if (primaryResult && primaryResult.success && primaryResult.models.length > 0) {
          populateModelDropdown("fallbackModel", primaryResult.models, curFallback || primaryResult.models[0]);
        }

        const count = primaryResult && primaryResult.models ? primaryResult.models.length : 0;
        setStatusMsg(`✓ Synced ${count} models.`, "success");
      } catch (err) {
        setStatusMsg("Sync failed: " + (err.message || err), "error");
      } finally {
        syncBtn.disabled = false;
        syncBtn.innerHTML = originalText;
      }
    });
  }

  // Save Settings Button
  const saveBtn = $("#saveSettingsBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const newConfig = {
        provider_type: $("#providerType") ? $("#providerType").value : "omniroute",
        base_url: $("#baseUrl") ? $("#baseUrl").value.trim() : "",
        api_key: $("#apiKey") ? $("#apiKey").value.trim() : "",
        ollama_base_url: $("#ollamaBaseUrl") ? $("#ollamaBaseUrl").value.trim() : "",
        primary_model: $("#primaryModel") ? $("#primaryModel").value : "",
        fallback_model: $("#fallbackModel") ? $("#fallbackModel").value : "",
        embedding_model: $("#embeddingModel") ? $("#embeddingModel").value.trim() : "",
        inbox_path: $("#config-inbox-path") ? $("#config-inbox-path").value.trim() : "D:/knowledge_inbox",
        faiss_path: $("#config-faiss-path") ? $("#config-faiss-path").value.trim() : "D:/Jarvis_QS/faiss_data",
      };

      try {
        saveBtn.disabled = true;
        const originalText = saveBtn.innerHTML;
        
        const res = await window.electronAPI.saveConfig(newConfig);
        if (res && res.success === false) {
          throw new Error(res.error || "Failed to save configuration");
        }

        saveBtn.textContent = "Saved! ✓";
        setStatusMsg("✓ Settings saved hot-swap!", "success");

        setTimeout(() => {
          saveBtn.innerHTML = originalText;
          saveBtn.disabled = false;
        }, 2000);
      } catch (err) {
        setStatusMsg("Save failed: " + (err.message || err), "error");
        saveBtn.disabled = false;
      }
    });
  }

  // Browse Buttons
  const btnBrowseInbox = $("#btn-browse-inbox");
  if (btnBrowseInbox) {
    btnBrowseInbox.addEventListener("click", async () => {
      const current = $("#config-inbox-path") ? $("#config-inbox-path").value : "";
      const path = await window.electronAPI.selectDirectory(current);
      if (path && $("#config-inbox-path")) {
        $("#config-inbox-path").value = path;
      }
    });
  }

  const btnBrowseFaiss = $("#btn-browse-faiss");
  if (btnBrowseFaiss) {
    btnBrowseFaiss.addEventListener("click", async () => {
      const current = $("#config-faiss-path") ? $("#config-faiss-path").value : "";
      const path = await window.electronAPI.selectDirectory(current);
      if (path && $("#config-faiss-path")) {
        $("#config-faiss-path").value = path;
      }
    });
  }

  // Vault Elements
  const vaultFileCount = document.getElementById("vault-file-count");
  const vaultLastSynced = document.getElementById("vault-last-synced");
  const btnSyncVault = document.getElementById("btn-sync-vault");
  const syncStatus = document.getElementById("vault-sync-status");

  // Load Stats
  async function refreshVaultStats() {
    if (window.electronAPI.getVaultStats) {
      const stats = await window.electronAPI.getVaultStats();
      if (vaultFileCount) vaultFileCount.textContent = stats.fileCount;
      if (vaultLastSynced) vaultLastSynced.textContent = stats.lastSynced;
    }
  }

  // Trigger Sync
  if (btnSyncVault) {
    btnSyncVault.addEventListener("click", async () => {
      btnSyncVault.disabled = true;
      btnSyncVault.textContent = "Syncing...";
      if (syncStatus) syncStatus.textContent = "Sync process started. Check AI Console for logs.";

      // Switch to Console Tab so user sees logs
      const consoleTabButton = document.querySelector('[data-panel="console"]');
      if (consoleTabButton) {
        consoleTabButton.click();
      }

      await window.electronAPI.startVaultSync();
    });
  }

  // Listen for Sync Logs
  if (window.electronAPI.onSyncLog) {
    window.electronAPI.onSyncLog((logData) => {
      const consoleOutput = document.getElementById("console-output") || document.querySelector(".console-content");
      if (consoleOutput) {
        const line = document.createElement("div");
        line.textContent = logData;
        consoleOutput.appendChild(line);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
      }
    });
  }

  // Sync Complete
  if (window.electronAPI.onSyncComplete) {
    window.electronAPI.onSyncComplete((result) => {
      if (btnSyncVault) {
        btnSyncVault.disabled = false;
        btnSyncVault.textContent = "⚡ Sync Knowledge Vault";
      }
      if (syncStatus) {
        syncStatus.textContent = result.exitCode === 0 ? "✅ Sync Complete" : `❌ Sync Failed (Code: ${result.exitCode})`;
      }
      refreshVaultStats();
    });
  }

  // Initial Vault Stats refresh
  refreshVaultStats();

  // === Initial Load ===
  await loadConfig();

  // Dynamic Welcome Message Greeting Rotation
  const initialBubble = document.querySelector("#chatContainer .chat-bubble.message-bubble.ai-message");
  if (initialBubble) {
    const greetings = [
      "Online. Ready to assist.",
      "System active. Accessing FAISS Vault and LangGraph Orchestration.",
      "Jarvis QS initialized. What project or structural documents are we analyzing today?",
      "Quantum Shell operational. Standing by for query inputs...",
      "Cognitive core ready. Let's dig into engineering models, schedules, or specifications."
    ];
    const randomIdx = Math.floor(Math.random() * greetings.length);
    initialBubble.textContent = greetings[randomIdx];
  }

})();
