(async function () {
  // Prevent double-init
  if (window._jarvisInitialized) return;
  window._jarvisInitialized = true;

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  // ============================================================
  // LOG ROUTING: Route background logs to Debug Console / Output
  // ============================================================
  function logToDebugConsole(message) {
      const debugPane = document.getElementById("view-debug");
      if (debugPane) {
          const timestamp = new Date().toLocaleTimeString();
          debugPane.innerHTML += `<div style="color: #9cdcfe; font-family: monospace; font-size: 12px;">[${timestamp}] ${message}</div>`;
          debugPane.scrollTop = debugPane.scrollHeight;
      }
  }

  function logToOutputPanel(message) {
      const outputPane = document.getElementById("view-output");
      if (outputPane) {
          const timestamp = new Date().toLocaleTimeString();
          outputPane.innerHTML += `<div style="color: #d4d4d4; font-family: monospace; font-size: 12px;">[${timestamp}] ${message}</div>`;
          outputPane.scrollTop = outputPane.scrollHeight;
      }
  }

  // Expose globally for external use
  window.logToDebugConsole = logToDebugConsole;
  window.logToOutputPanel = logToOutputPanel;

  // Robust Event Delegation & Initialization
  function runOnDOMReady(callback) {
      if (document.readyState === "complete" || document.readyState === "interactive") {
          callback();
      } else {
          document.addEventListener("DOMContentLoaded", callback);
      }
  }

  runOnDOMReady(() => {
      console.log("Initializing Jarvis QS UI click handlers...");

      // Global click delegation to ensure dynamic elements always respond
      document.body.addEventListener("click", (e) => {
          const target = e.target.closest('[data-action], .panel-tab-item, .term-instance-pill, .panel-tool-btn, .win-btn');
          if (!target) return;

          // Handle generic tool buttons or tabs safely
          // console.log("Clicked interactive element:", target);
      });

      // Fix Sidebar Explorer Tree Item Clicks
      document.querySelectorAll(".explorer-tree-item, .file-item, .tree-item").forEach(item => {
          item.addEventListener("click", async (e) => {
              e.stopPropagation();
              const filePath = item.dataset.path || (item.querySelector('.tree-label') ? item.querySelector('.tree-label').textContent : null);
              if (filePath) {
                  console.log("Opening file from explorer:", filePath);
                  // Highlight item
                  document.querySelectorAll(".explorer-tree-item, .file-item, .tree-item").forEach(el => el.classList.remove("active"));
                  item.classList.add("active");
                  const parts = filePath.split(/[\\/]/);
                  const fileName = parts[parts.length - 1];
                  try {
                      await openFileInEditor(filePath, fileName);
                  } catch (err) {
                      console.error("Failed to open file from click:", err);
                  }
              }
          });
      });
  });


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
  // --- 1. RICH MARKDOWN FORMATTING HELPER ---
  function renderMarkdownMessage(rawText) {
      if (!rawText) return "";
      try {
          if (typeof marked !== 'undefined') {
              marked.setOptions({ gfm: true, breaks: true });
              return marked.parse(rawText);
          }
      } catch (err) {
          console.error("Markdown parsing error:", err);
      }
      return rawText
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>')
          .replace(/\n/g, '<br>');
  }

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
    <p>${renderMarkdownMessage(thoughtContent)}</p>
</details>
`;
      return detailsHtml + "\n\n" + renderMarkdownMessage(cleanedText);
    }

    return renderMarkdownMessage(rawText);
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
      bubble.innerHTML = processedText;
    } else if (role === "user") {
      bubble.innerHTML = renderMarkdownMessage(processedText);
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

  // Track chat history and greeting rotation
  let chatHistory = [];

  const startupGreetings = [
      "Online. Ready to assist with project documentation, specifications, and BoQs.",
      "System active. Accessing FAISS Knowledge Vault and LangGraph Orchestration.",
      "Jarvis QS initialized. What engineering documents or project rates are we reviewing today?",
      "Quantum Shell operational. Standing by for query inputs...",
      "Cognitive core ready. Let's analyze engineering models, takeoffs, or specifications."
  ];

  // Track current active message bubble elements during a stream
  let activeAiBubble = null;
  let activeStepCard = null;
  let activeStepBody = null;
  let activeAnswerContent = null;
  let stepCounter = 0;

  // Memory Compression: Combines Sliding Window (recent 4) + Older Summaries
  function getOptimizedHistory() {
      if (chatHistory.length <= 6) {
          return chatHistory;
      }
      const olderMessages = chatHistory.slice(0, chatHistory.length - 4);
      const recentMessages = chatHistory.slice(-4);

      const summaryString = olderMessages
          .map(m => `${m.role === 'user' ? 'User' : 'Jarvis'}: ${m.content.substring(0, 80).replace(/\n/g, ' ')}...`)
          .join(" | ");

      return [
          {
              role: "system",
              content: `[Background Conversation Context & History Summary: ${summaryString}]`
          },
          ...recentMessages
      ];
  }

  function initializeStreamingBubble() {
      const chatContainer = getChatContainer();
      if (!chatContainer) return;

      stepCounter = 0;
      const wasPinned = isScrolledToBottom();

      // Silently close older suggestion chips
      $$(".suggestion-chips").forEach(box => box.classList.add("closed"));

      const wrap = document.createElement("div");
      wrap.className = "chat-message assistant";

      const avatar = document.createElement("div");
      avatar.className = "chat-avatar";
      avatar.textContent = "J";

      activeAiBubble = document.createElement('div');
      activeAiBubble.className = 'message-bubble ai-message';

      activeStepCard = document.createElement('div');
      activeStepCard.className = 'agent-step-card expanded';

      const header = document.createElement('div');
      header.className = 'agent-step-header';
      header.innerHTML = `
          <svg class="step-chevron" viewBox="0 0 24 24" width="9" height="9" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
          <span class="thinking-dot"></span>
          <span class="step-title">Thinking...</span>
      `;

      header.addEventListener('click', function() {
          const card = this.closest('.agent-step-card');
          if (card) {
              card.classList.toggle('expanded');
          }
      });

      activeStepBody = document.createElement('div');
      activeStepBody.className = 'agent-step-body';
      activeStepBody.style.display = 'block';

      activeStepCard.appendChild(header);
      activeStepCard.appendChild(activeStepBody);
      activeAiBubble.appendChild(activeStepCard);

      activeAnswerContent = document.createElement('div');
      activeAnswerContent.className = 'markdown-body answer-text';
      activeAnswerContent.style.whiteSpace = 'pre-wrap';
      activeAiBubble.appendChild(activeAnswerContent);

      wrap.appendChild(avatar);
      wrap.appendChild(activeAiBubble);
      chatContainer.appendChild(wrap);

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
      chatHistory.push({ role: "user", content: text });

      inputEl.value = "";
      inputEl.disabled = true;
      if (sendBtn) sendBtn.disabled = true;

      activeAiBubble = null;
      activeStepCard = null;
      activeStepBody = null;
      activeAnswerContent = null;

      initializeStreamingBubble();

      try {
          const optimizedHistory = getOptimizedHistory();
          await window.electronAPI.askJarvisStream({ prompt: text, history: optimizedHistory });
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
          activeAnswerContent.dataset.rawText = (activeAnswerContent.dataset.rawText || "") + event.content;
          activeAnswerContent.innerHTML = renderMarkdownMessage(activeAnswerContent.dataset.rawText);
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

          const activeHeader = activeStepCard ? activeStepCard.querySelector('.agent-step-header') : null;
          if (activeHeader) {
              activeHeader.innerHTML = `
                  <svg class="step-chevron" viewBox="0 0 24 24" width="9" height="9" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
                  <span class="step-title">Thought process</span>
                  <span class="step-status-text">(${stepCounter} steps)</span>
              `;
          }

          if (activeStepCard) activeStepCard.classList.remove("expanded");

          let finalAnswerText = activeAnswerContent ? (activeAnswerContent.dataset.rawText || activeAnswerContent.textContent) : activeAiBubble.innerText;
          
          // Clean out suggestions tag if it exists in the streamed answer text
          const suggestionRegex = /\[SUGGESTIONS:\s*(.*?)\]/i;
          const match = finalAnswerText.match(suggestionRegex);
          if (match) {
              finalAnswerText = finalAnswerText.replace(match[0], '').trim();
          }
          if (activeAnswerContent) {
              activeAnswerContent.dataset.rawText = finalAnswerText;
              activeAnswerContent.innerHTML = renderMarkdownMessage(finalAnswerText);
          }

          chatHistory.push({ role: "assistant", content: finalAnswerText });

          const actionsContainer = document.createElement('div');
          actionsContainer.className = 'response-actions';
          const copyBtn = document.createElement('button');
          copyBtn.className = 'copy-btn';
          copyBtn.innerHTML = `<svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" fill="none" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> Copy`;
          copyBtn.onclick = () => {
              navigator.clipboard.writeText(finalAnswerText).then(() => {
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

          const suggestionsBox = document.createElement('div');
          suggestionsBox.className = 'suggestion-chips';

          let followUps = ["Check another project", "List available source files", "Extract pricing data"];
          const lower = finalAnswerText.toLowerCase();
          if (lower.includes("concrete") || lower.includes("reinforcement")) {
              followUps = ["Check steel tonnage", "Search structural specifications", "List concrete mix ratios"];
          } else if (lower.includes("hospital") || lower.includes("school")) {
              followUps = ["View contract details", "Check project variations", "List package documents"];
          }

          followUps.forEach(pText => {
              const chip = document.createElement('button');
              chip.className = 'suggestion-chip';
              chip.textContent = pText;
              chip.onclick = () => {
                  if (inputField) {
                      inputField.value = pText;
                      if (sendButton) sendButton.click();
                  }
              };
              suggestionsBox.appendChild(chip);
          });
          activeAiBubble.appendChild(suggestionsBox);

          if (inputField) inputField.disabled = false;
          if (sendButton) sendButton.disabled = false;
          if (inputField) inputField.focus();

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
      // Handled via the main terminal-log IPC handler
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

  // Monaco Editor & File Explorer Logic
  let editorInstance = null;

  function initMonacoEditor() {
      return new Promise((resolve) => {
          if (typeof require === 'undefined') {
              console.error("Monaco loader.js not loaded yet.");
              resolve(null);
              return;
          }
          require(['vs/editor/editor.main'], function() {
              const welcomePanel = document.getElementById("panel-welcome");
              if (welcomePanel) {
                  welcomePanel.style.display = "none";
                  welcomePanel.classList.remove("active");
              }

              const editorContent = document.querySelector(".editor-content");
              let codePanel = document.getElementById("panel-code-editor");
              if (!codePanel) {
                  codePanel = document.createElement("div");
                  codePanel.className = "tab-panel active";
                  codePanel.id = "panel-code-editor";
                  codePanel.style.width = "100%";
                  codePanel.style.height = "100%";
                  
                  const container = document.createElement("div");
                  container.id = "monaco-editor-container";
                  container.style.width = "100%";
                  container.style.height = "100%";
                  
                  codePanel.appendChild(container);
                  editorContent.appendChild(codePanel);
              } else {
                  codePanel.style.display = "block";
                  codePanel.classList.add("active");
              }

              const container = document.getElementById("monaco-editor-container");
              editorInstance = monaco.editor.create(container, {
                  value: "",
                  language: "python",
                  theme: "vs-dark",
                  automaticLayout: true
              });
              resolve(editorInstance);
          });
      });
  }

  const openTabs = [];
  let activeTabPath = null;
  const BINARY_EXTENSIONS = ['.sqlite', '.pkl', '.faiss', '.db', '.zip', '.png', '.jpg', '.pdf', '.exe', '.bin', '.sqlite3', '.tar', '.gz'];

  async function openFileInEditor(filePath, fileName) {
      if (!editorInstance) {
          await initMonacoEditor();
      }

      const lowerName = fileName.toLowerCase();
      const ext = lowerName.substring(lowerName.lastIndexOf('.'));
      
      // Manage/retrieve content. For binary files, use placeholder notice
      let content = "";
      const isBinary = BINARY_EXTENSIONS.includes(ext);
      if (isBinary) {
          content = `[Jarvis QS Notice]: Binary file format (${ext}). Cannot be displayed as plain text in editor.`;
      } else {
          const res = await window.electronAPI.readFileContent(filePath);
          if (!res.success) {
              console.error("Failed to read file content:", res.error);
              return;
          }
          content = res.content;
      }

      let lang = "plaintext";
      if (lowerName.endsWith(".js")) lang = "javascript";
      else if (lowerName.endsWith(".py")) lang = "python";
      else if (lowerName.endsWith(".json")) lang = "json";
      else if (lowerName.endsWith(".css")) lang = "css";
      else if (lowerName.endsWith(".html")) lang = "html";
      else if (lowerName.endsWith(".md")) lang = "markdown";

      // Manage openTabs array
      let existingTab = openTabs.find(t => t.path === filePath);
      if (!existingTab) {
          // Create Monaco Model
          const model = monaco.editor.createModel(content, lang);
          existingTab = {
              path: filePath,
              name: fileName,
              model: model
          };
          openTabs.push(existingTab);
      }

      activeTabPath = filePath;

      // Set model in editor
      editorInstance.setModel(existingTab.model);

      // Render tab bar
      renderEditorTabBar();

      // Show editor panels
      const welcomePanel = document.getElementById("panel-welcome");
      if (welcomePanel) {
          welcomePanel.style.display = "none";
          welcomePanel.classList.remove("active");
      }

      let codePanel = document.getElementById("panel-code-editor");
      if (codePanel) {
          codePanel.style.display = "block";
          codePanel.classList.add("active");
      }

      // Highlight active file in explorer tree
      document.querySelectorAll(".tree-item").forEach(el => {
          if (el.dataset.path === filePath) {
              el.classList.add("active");
          } else {
              el.classList.remove("active");
          }
      });
  }

  function renderEditorTabBar() {
      const tabsContainer = document.querySelector(".workspace-main .tabs");
      if (!tabsContainer) return;

      tabsContainer.innerHTML = "";
      
      openTabs.forEach((tab, index) => {
          const tabEl = document.createElement("div");
          tabEl.className = "tab" + (tab.path === activeTabPath ? " active" : "");
          tabEl.dataset.path = tab.path;
          
          tabEl.innerHTML = `
              <span class="tab-label">${tab.name}</span>
              <span class="tab-icon codicon codicon-close" data-close-path="${tab.path}"></span>
          `;
          
          // Use a keypress or click handler to switch
          tabEl.onclick = (e) => {
              // Avoid switching if we clicked the close icon
              if (e.target.classList.contains("codicon-close")) return;
              openFileInEditor(tab.path, tab.name);
          };
          
          const closeBtn = tabEl.querySelector(`[data-close-path]`);
          if (closeBtn) {
              closeBtn.onclick = (e) => {
                  e.stopPropagation();
                  // Remove from tabs list
                  const removed = openTabs.splice(index, 1)[0];
                  if (removed && removed.model) {
                      try {
                          removed.model.dispose(); // prevent memory leak
                      } catch (err) {
                          console.error("Error disposing model:", err);
                      }
                  }
                  
                  if (activeTabPath === tab.path) {
                      if (openTabs.length > 0) {
                          const nextIdx = Math.min(index, openTabs.length - 1);
                          const nextActive = openTabs[nextIdx];
                          openFileInEditor(nextActive.path, nextActive.name);
                      } else {
                          activeTabPath = null;
                          showWelcomeTab();
                      }
                  } else {
                      renderEditorTabBar();
                  }
              };
          }
          
          tabsContainer.appendChild(tabEl);
      });

      if (openTabs.length === 0) {
          showWelcomeTab();
      }
  }

  function showWelcomeTab() {
      const tabsContainer = document.querySelector(".workspace-main .tabs");
      if (tabsContainer) {
          tabsContainer.innerHTML = `
              <div class="tab active" data-tab="welcome">
                  <span class="tab-label">Welcome</span>
                  <span class="tab-icon codicon codicon-close"></span>
              </div>
          `;
      }
      
      const codePanel = document.getElementById("panel-code-editor");
      if (codePanel) {
          codePanel.style.display = "none";
          codePanel.classList.remove("active");
      }

      const welcomePanel = document.getElementById("panel-welcome");
      if (welcomePanel) {
          welcomePanel.style.display = "block";
          welcomePanel.classList.add("active");
      }
  }

  async function loadWorkspaceExplorer() {
      const res = await window.electronAPI.getWorkspaceFiles();
      if (!res.success) {
          console.error("Failed to load workspace files:", res.error);
          return;
      }

      const treeContainer = document.querySelector(".sidebar-tree");
      if (!treeContainer) return;
      treeContainer.innerHTML = "";

      const rootItem = document.createElement("div");
      rootItem.className = "tree-item expanded";
      rootItem.innerHTML = `
          <span class="codicon codicon-chevron-down tree-chevron"></span>
          <span class="codicon codicon-folder tree-icon"></span>
          <span class="tree-label">Jarvis_QS</span>
      `;
      treeContainer.appendChild(rootItem);

      const childrenContainer = document.createElement("div");
      childrenContainer.className = "tree-children";
      childrenContainer.style.display = "flex";
      childrenContainer.style.flexDirection = "column";
      treeContainer.appendChild(childrenContainer);

      rootItem.onclick = (e) => {
          e.stopPropagation();
          const isExpanded = childrenContainer.style.display !== "none";
          childrenContainer.style.display = isExpanded ? "none" : "flex";
          const chevronIcon = rootItem.querySelector(".tree-chevron");
          if (chevronIcon) {
              chevronIcon.className = isExpanded
                  ? "codicon codicon-chevron-right tree-chevron"
                  : "codicon codicon-chevron-down tree-chevron";
          }
      };

      function buildTreeHTML(items, parentElement) {
          items.forEach(item => {
              const itemEl = document.createElement("div");
              itemEl.className = "tree-item";
              
              const depth = item.path.split(/[\\/]/).length;
              itemEl.style.paddingLeft = `${depth * 10 + 6}px`;

              let iconClass = "codicon-file";
              if (item.isDirectory) {
                  iconClass = "codicon-folder";
              } else if (item.name.endsWith(".json")) {
                  iconClass = "codicon-file-code";
              } else if (item.name.endsWith(".py")) {
                  iconClass = "codicon-file-code";
              } else if (item.name.endsWith(".js")) {
                  iconClass = "codicon-file-code";
              } else if (item.name.endsWith(".css")) {
                  iconClass = "codicon-file-code";
              } else if (item.name.endsWith(".html")) {
                  iconClass = "codicon-file-code";
              }

              const chevron = item.isDirectory 
                  ? `<span class="codicon codicon-chevron-down tree-chevron"></span>` 
                  : `<span class="tree-chevron-spacer" style="width: 16px; display: inline-block;"></span>`;

              itemEl.innerHTML = `
                  ${chevron}
                  <span class="codicon ${iconClass} tree-icon"></span>
                  <span class="tree-label">${item.name}</span>
              `;
              
              parentElement.appendChild(itemEl);

              if (item.isDirectory && item.children) {
                  const subChildrenContainer = document.createElement("div");
                  subChildrenContainer.className = "tree-children";
                  parentElement.appendChild(subChildrenContainer);
                  
                  itemEl.onclick = (e) => {
                      e.stopPropagation();
                      const isExpanded = subChildrenContainer.style.display !== "none";
                      subChildrenContainer.style.display = isExpanded ? "none" : "block";
                      const chevronIcon = itemEl.querySelector(".tree-chevron");
                      if (chevronIcon) {
                          chevronIcon.className = isExpanded 
                              ? "codicon codicon-chevron-right tree-chevron" 
                              : "codicon codicon-chevron-down tree-chevron";
                      }
                  };

                  buildTreeHTML(item.children, subChildrenContainer);
              } else {
                  itemEl.onclick = async (e) => {
                      e.stopPropagation();
                      document.querySelectorAll(".tree-item").forEach(el => el.classList.remove("active"));
                      itemEl.classList.add("active");
                      await openFileInEditor(item.path, item.name);
                  };
              }
          });
      }

      buildTreeHTML(res.files, childrenContainer);
  }

  // Initial Vault Stats refresh
  refreshVaultStats();

  // ==========================================================
  // SECTION 7: VS Code-Style Integrated Terminal Drawer
  // ==========================================================
  function logToTerminal(text, type = "stdout", targetTermId = null) {
    let termId = targetTermId;
    if (!termId) {
        const activeTab = document.querySelector(".term-instance-pill.active, .terminal-tab.active, [data-term].active") || document.querySelector("[data-term]");
        termId = activeTab ? (activeTab.dataset.term || activeTab.getAttribute("data-term") || "1") : "1";
    }

    const inst = terminals[termId];
    if (inst && inst.term) {
        const formatted = text.replace(/\r?\n/g, "\r\n");
        inst.term.write(formatted);
    }
  }

  // Intercept window console.log and errors to also show in terminal
  const originalLog = console.log;
  console.log = function(...args) {
    originalLog.apply(console, args);
    logToTerminal(args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' '), "info");
  };

  const originalError = console.error;
  console.error = function(...args) {
    originalError.apply(console, args);
    logToTerminal(args.map(a => typeof a === 'object' ? JSON.stringify(a) : a).join(' '), "stderr");
  };

  // Hook up Clear and Auto-scroll buttons
  document.getElementById("clearTerminalBtn")?.addEventListener("click", () => {
    const termOutput = document.querySelector(".terminal-instance-pane.active");
    if (termOutput) termOutput.innerHTML = "";
  });

  let autoScrollState = true;
  const toggleScrollBtn = document.getElementById("toggleAutoScrollBtn");
  if (toggleScrollBtn) {
    toggleScrollBtn.addEventListener("click", () => {
      autoScrollState = !autoScrollState;
      window._terminalAutoScroll = autoScrollState;
      toggleScrollBtn.textContent = `Auto-scroll: ${autoScrollState ? 'ON' : 'OFF'}`;
    });
  }

  // Bind terminal input bar to send commands to the active PTY process
  const terminalInput = document.querySelector(".terminal-input-bar input, #terminalInput, input[placeholder*='terminal command']");

  if (terminalInput) {
      terminalInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
              const command = terminalInput.value;
              if (!command.trim()) return;

              // Robust fallback to find any active terminal tab or default to '1'
              const activeTab = document.querySelector(".term-instance-pill.active, .terminal-tab.active, [data-term].active") || document.querySelector("[data-term]");
              const termId = activeTab ? (activeTab.dataset.term || activeTab.getAttribute("data-term") || "1") : "1";

              console.log(`Sending command to terminal ${termId}: ${command}`);

              if (window.electronAPI && window.electronAPI.writeTerminal) {
                  window.electronAPI.writeTerminal(termId, command + "\n");
              }

              terminalInput.value = "";
          }
      });
  }

  // VS Code Bottom Panel Controller
  function initWorkspaceBottomPanel() {
    const panel = document.getElementById("workspaceBottomPanel");
    if (!panel) return;

    // 1. Tab Switching
    const tabs = document.querySelectorAll(".panel-tab-item");
    const views = document.querySelectorAll(".panel-content-body > .panel-view");

    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            views.forEach(v => {
                v.style.display = "none";
                v.classList.remove("active");
            });

            tab.classList.add("active");
            const target = document.getElementById(`view-${tab.dataset.target}`);
            if (target) {
                target.style.display = tab.dataset.target === "terminal" ? "flex" : "block";
                target.classList.add("active");
            }
            panel.classList.remove("collapsed");
        });
    });

    // 2. Close / Collapse (✕)
    document.getElementById("closePanelBtn")?.addEventListener("click", () => {
        panel.classList.toggle("collapsed");
    });

    // 3. Maximize / Restore (🗖)
    let isMaximized = false;
    document.getElementById("togglePanelSizeBtn")?.addEventListener("click", () => {
        isMaximized = !isMaximized;
        panel.style.height = isMaximized ? "85vh" : "220px";
        panel.classList.remove("collapsed");
    });

    // 4. Drag-to-Resize Handle
    const handle = document.getElementById("panelResizeHandle");
    let isResizing = false;
    if (handle) {
        handle.addEventListener("mousedown", (e) => {
            isResizing = true;
            document.body.style.cursor = "ns-resize";
            e.preventDefault();
        });
        window.addEventListener("mousemove", (e) => {
            if (!isResizing) return;
            const newHeight = window.innerHeight - e.clientY;
            if (newHeight >= 80 && newHeight <= window.innerHeight * 0.85) {
                panel.style.height = `${newHeight}px`;
                panel.classList.remove("collapsed");
            }
        });
        window.addEventListener("mouseup", () => {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = "default";
            }
        });
    }

    // 5. Terminal Instance Management (+ / ✕ / Kill)
    const bar = document.getElementById("terminalInstancesBar");
    const panesContainer = document.getElementById("terminalPanesContainer");
    let terminalCount = 1;

    function bindTerminalClose(pill, termId) {
        const closeBtn = pill.querySelector(".term-close-btn");
        if (!closeBtn) return;
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            if (bar.querySelectorAll(".term-instance-pill").length <= 1) return;

            document.getElementById(`termPane-${termId}`)?.remove();
            pill.remove();

            // Clean up the backend process
            if (window.electronAPI && window.electronAPI.killTerminal) {
                window.electronAPI.killTerminal(termId);
            }

            const remaining = bar.querySelectorAll(".term-instance-pill");
            if (remaining.length > 0) remaining[remaining.length - 1].click();
        };
    }

    function spawnShellForTab(tabIndex, shellType) {
        let executable = "powershell.exe";

        if (shellType.toLowerCase().includes("command prompt") || shellType.toLowerCase().includes("cmd")) {
            executable = "cmd.exe";
        } else if (shellType.toLowerCase().includes("git bash") || shellType.toLowerCase().includes("bash")) {
            executable = "bash.exe";
        }

        console.log(`Creating terminal tab ${tabIndex} with binary: ${executable}`);
        window.electronAPI?.createTerminal?.(tabIndex, executable);
    }
    window.spawnShellForTab = spawnShellForTab;

    function createNewTerminalTab(shell, name) {
        // Fallback mapping if shell name is passed instead of executable
        if (!name) {
            name = shell;
            const lowerShell = shell.toLowerCase();
            if (lowerShell.includes("powershell")) {
                shell = "powershell.exe";
            } else if (lowerShell.includes("prompt") || lowerShell.includes("cmd")) {
                shell = "cmd.exe";
            } else if (lowerShell.includes("bash") || lowerShell.includes("git")) {
                shell = "bash.exe";
            }
        }
        
        // Match executable and prompt prefix based on selection
        let executable = shell;
        let promptPrefix = "PS D:\\Jarvis_QS>";
        const lowerName = (name || "").toLowerCase();
        const lowerShellPath = (shell || "").toLowerCase();
        
        if (lowerName.includes("prompt") || lowerName.includes("cmd") || lowerShellPath.includes("cmd")) {
            executable = "cmd.exe";
            promptPrefix = "D:\\Jarvis_QS>";
        } else if (lowerName.includes("bash") || lowerName.includes("git") || lowerShellPath.includes("bash")) {
            executable = "bash.exe";
            promptPrefix = "bash-5.1$";
        } else if (lowerName.includes("powershell") || lowerShellPath.includes("powershell")) {
            executable = "powershell.exe";
            promptPrefix = "PS D:\\Jarvis_QS>";
        }

        terminalCount++;
        const termId = terminalCount;

        // Create pill (tab button)
        const pill = document.createElement("button");
        pill.className = "term-instance-pill";
        pill.dataset.term = termId;
        pill.innerHTML = `
            <span>${termId}: ${name}</span>
            <span class="term-close-btn" data-term="${termId}">✕</span>
        `;

        // Create terminal pane
        const pane = document.createElement("div");
        pane.id = `termPane-${termId}`;
        pane.className = "terminal-instance-pane";
        pane.style.height = "100%";
        pane.style.overflowY = "auto";
        pane.style.padding = "8px";
        pane.style.boxSizing = "border-box";
        pane.style.fontFamily = "monospace";
        pane.style.whiteSpace = "pre-wrap";
        pane.innerHTML = `<div style="color: #60a5fa;">${promptPrefix} Loading active terminal ${termId}...</div>`;

        panesContainer.appendChild(pane);
        bar.appendChild(pill);

        // Switch to new terminal
        bar.querySelectorAll(".term-instance-pill").forEach(p => p.classList.remove("active"));
        panesContainer.querySelectorAll(".terminal-instance-pane").forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        pane.classList.add("active");

        // Initialize xterm.js instance
        initTerminalInstance(termId);

        // Spawn backend process
        spawnShellForTab(termId, name || shell);

        // Bind switch tab
        pill.onclick = () => {
            bar.querySelectorAll(".term-instance-pill").forEach(p => p.classList.remove("active"));
            panesContainer.querySelectorAll(".terminal-instance-pane").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            pane.classList.add("active");
        };

        // Bind close button
        bindTerminalClose(pill, termId);
    }

    // Expose it globally so the dropdown items can find & call it
    window.createNewTerminalTab = createNewTerminalTab;

    // Redundant static tab 1 layout initialization removed - handled by downstream IPC terminal binder

    // Wire profile selector dropdown (+ ▾)
    const addTermBtn = document.getElementById("addTerminalBtn");
    addTermBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        closeAllDropdowns();

        const rect = addTermBtn.getBoundingClientRect();

        const dropdown = document.createElement("div");
        dropdown.className = "terminal-dropdown-menu";
        dropdown.style.left = `${rect.left}px`;
        dropdown.style.top = `${rect.bottom + window.scrollY}px`;
        
        const profiles = [
            { name: "PowerShell", shell: "powershell.exe" },
            { name: "Command Prompt", shell: "cmd.exe" },
            { name: "Git Bash", shell: "bash.exe" }
        ];

        profiles.forEach(p => {
            const item = document.createElement("div");
            item.className = "terminal-dropdown-item";
            item.textContent = p.name;
            item.onclick = async () => {
                await createNewTerminalTab(p.shell, p.name.toLowerCase());
                dropdown.remove();
            };
            dropdown.appendChild(item);
        });

        document.body.appendChild(dropdown);
    });

    // Cleanup original static terminal code

    // Wire triple dot action menu (⋯)
    const overflowBtn = document.getElementById("panelOverflowBtn");
    overflowBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        closeAllDropdowns();

        const rect = overflowBtn.getBoundingClientRect();

        const dropdown = document.createElement("div");
        dropdown.className = "terminal-dropdown-menu";
        dropdown.style.left = `${rect.left - 100}px`;
        dropdown.style.top = `${rect.bottom + window.scrollY}px`;
        
        const actions = [
            {
                name: "Clear Terminal",
                action: () => {
                    const activePane = document.querySelector(".terminal-instance-pane.active");
                    if (activePane) activePane.innerHTML = "";
                }
            },
            {
                name: "Run Active File",
                action: () => {
                    const activeTab = document.querySelector(".workspace-main .tab.active");
                    if (activeTab && activeTab.dataset.tab === "code-editor") {
                        const activeLabel = activeTab.querySelector(".tab-label")?.textContent;
                        if (activeLabel) {
                            const activePill = document.querySelector(".term-instance-pill.active");
                            if (activePill) {
                                const termId = parseInt(activePill.dataset.term, 10);
                                let cmd = `python ${activeLabel}`;
                                if (activeLabel.endsWith(".py")) {
                                    cmd = `python ${activeLabel}`;
                                } else if (activeLabel.endsWith(".js")) {
                                    cmd = `node ${activeLabel}`;
                                } else {
                                    cmd = `./${activeLabel}`;
                                }
                                window.electronAPI.writeTerminal({ id: termId, text: cmd });
                            }
                        }
                    } else {
                        alert("No active code file open in editor!");
                    }
                }
            },
            {
                name: "Start Dictation",
                action: () => {
                    alert("Dictation mode activated. Standard input listening...");
                }
            }
        ];

        actions.forEach(act => {
            const item = document.createElement("div");
            item.className = "terminal-dropdown-item";
            item.textContent = act.name;
            item.onclick = () => {
                act.action();
                dropdown.remove();
            };
            dropdown.appendChild(item);
        });

        document.body.appendChild(dropdown);
    });

    function closeAllDropdowns() {
        document.querySelectorAll(".terminal-dropdown-menu").forEach(d => d.remove());
    }

    document.addEventListener("click", closeAllDropdowns);

    // Bind initial tab 1 Close and IPC
    const initialPill = bar ? bar.querySelector('[data-term="1"]') : document.querySelector('[data-term="1"]');
    if (initialPill) {
        // Initialize xterm.js instance
        initTerminalInstance(1);

        spawnShellForTab(1, "powershell.exe");

        initialPill.onclick = () => {
            if (bar) {
                bar.querySelectorAll(".term-instance-pill").forEach(p => p.classList.remove("active"));
            }
            if (panesContainer) {
                panesContainer.querySelectorAll(".terminal-instance-pane").forEach(pane => pane.classList.remove("active"));
            }
            initialPill.classList.add("active");
            document.getElementById("termPane-1")?.classList.add("active");
        };
        bindTerminalClose(initialPill, 1);
    }

    // Kill Active Terminal Button (🗑)
    document.getElementById("killTerminalBtn")?.addEventListener("click", () => {
        const activePill = bar?.querySelector(".term-instance-pill.active");
        if (activePill) {
            activePill.querySelector(".term-close-btn")?.click();
        }
    });

    // Split Terminal (⬌)
    document.getElementById("splitTerminalBtn")?.addEventListener("click", () => {
        logToTerminal("Split terminal action triggered (UI layout implementation pending).", "info");
    });
  }

  // Initialize the bottom panel controls
  initWorkspaceBottomPanel();

  // Listen to Terminal Logs in renderer.js
  if (window.electronAPI && window.electronAPI.onTerminalLog) {
    window.electronAPI.onTerminalLog((log) => {
      const text = log.text || "";
      const type = log.type || "";
      const termId = log.terminalId;
      
      const isBackgroundLog = (
          type === "stderr" || 
          text.includes("[DEBUG]") || 
          text.startsWith("[DEBUG]") || 
          text.trim().startsWith("[DEBUG]") || 
          text.includes("[OUTPUT]") ||
          text.startsWith("[OUTPUT]") || 
          text.trim().startsWith("[OUTPUT]") ||
          text.includes("HuggingFace") ||
          text.includes("embedding") ||
          text.includes("FAISS") ||
          text.includes("langchain") ||
          text.includes("LangGraph") ||
          text.includes("orchestrator") ||
          text.includes("tool execution") ||
          text.includes("Warning") ||
          text.includes("UserWarning") ||
          text.includes("DeprecationWarning") ||
          text.includes("daemon") ||
          text.includes("sync") ||
          text.includes("vault") ||
          text.includes("indexing") ||
          text.includes("ingestion")
      );

      if (isBackgroundLog) {
        // Route background logs to Debug Console and Output panels
        if (type === "stderr" || 
            text.includes("[DEBUG]") || 
            text.startsWith("[DEBUG]") || 
            text.trim().startsWith("[DEBUG]") || 
            text.includes("HuggingFace") ||
            text.includes("embedding") ||
            text.includes("FAISS") ||
            text.includes("langchain") ||
            text.includes("LangGraph") ||
            text.includes("orchestrator") ||
            text.includes("tool execution") ||
            text.includes("Warning") ||
            text.includes("UserWarning") ||
            text.includes("DeprecationWarning")) {
          logToDebugConsole(text);
        }
        
        // Route orchestrator/daemon logs to Output panel
        if (text.includes("[OUTPUT]") ||
            text.startsWith("[OUTPUT]") || 
            text.trim().startsWith("[OUTPUT]") || 
            text.includes("daemon") ||
            text.includes("sync") ||
            text.includes("vault") ||
            text.includes("indexing") ||
            text.includes("ingestion")) {
          logToOutputPanel(text);
        }
        return; // Diversion complete! Bypasses terminal writing.
      }

      // Otherwise, write normally to active/target user shell terminal
      logToTerminal(text, type, termId);
    });
  }

  // Load file explorer tree safely
  try {
    await loadWorkspaceExplorer();
  } catch (err) {
    console.error("Failed to load workspace explorer:", err);
  }

  // === Initial Load ===
  try {
    await loadConfig();
  } catch (err) {
    console.error("Failed to load configuration:", err);
  }

  // Dynamic Welcome Message Greeting Rotation safely
  try {
    const initialBubble = document.querySelector("#chatContainer .chat-bubble.message-bubble.ai-message");
    if (initialBubble && !initialBubble.dataset.initialized) {
      const randomGreeting = startupGreetings[Math.floor(Math.random() * startupGreetings.length)];
      initialBubble.textContent = randomGreeting;
      initialBubble.dataset.initialized = "true";
      chatHistory.push({ role: "assistant", content: randomGreeting });
    }
  } catch (err) {
    console.error("Failed to rotate greeting message:", err);
  }

})();
