const { app, BrowserWindow, ipcMain, Menu } = require("electron");
const path = require("path");
const fs = require("fs");
const { execFile, spawn } = require("child_process");
const pty = require("node-pty");

const dev = process.argv.includes("--dev");
const configPath = path.join(__dirname, "user_config.json");

const DEFAULT_CONFIG = {
  provider_type: "omniroute",
  primary_model: "jarvis_brain",
  fallback_model: "qwen2.5-coder:3b-instruct-q4_K_M",
  base_url: "http://omni.dhanrickeviota.com/v1",
  api_key: "sk-9e731d7385077d7e-2cbf0c-598b3170",
  ollama_base_url: "http://localhost:11434/v1",
  embedding_model: "mistral/mistral/mistral-embed"
};

function readConfig() {
  if (fs.existsSync(configPath)) {
    try {
      const raw = fs.readFileSync(configPath, "utf-8");
      return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
    } catch (e) {
      return DEFAULT_CONFIG;
    }
  }
  return DEFAULT_CONFIG;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    backgroundColor: "#0b0f19",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true
    },
  });

  win.loadFile(path.join(__dirname, "index.html"));

  // Remove or comment out unconditional auto-opening:
  // win.webContents.openDevTools();

  // Optional: Only open DevTools in explicit development/debug mode
  if (process.argv.includes('--debug') || process.env.NODE_ENV === 'development') {
    win.webContents.openDevTools();
  }

  // Window Control listeners
  ipcMain.on("window-minimize", () => {
    if (win) win.minimize();
  });
  
  ipcMain.on("window-maximize", () => {
    if (win) {
      if (win.isMaximized()) {
        win.unmaximize();
      } else {
        win.maximize();
      }
    }
  });

  ipcMain.on("window-close", () => {
    if (win) win.close();
  });
}

app.whenReady().then(() => {
  // Remove native File/Edit menu
  Menu.setApplicationMenu(null);
  
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

let pythonDaemon = null;
let stdoutBuffer = "";

function getDaemonInstance(win) {
  if (!pythonDaemon) {
    console.log("Starting python warm-standby daemon...");
    const scriptPath = path.join(__dirname, "core", "orchestrator_cli.py");
    pythonDaemon = spawn("python", [scriptPath, "--daemon"], {
      cwd: __dirname,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        TRANSFORMERS_VERBOSITY: "error",
        HF_HUB_DISABLE_PROGRESS_BARS: "1"
      }
    });

    pythonDaemon.stdout.on("data", (data) => {
      stdoutBuffer += data.toString();
      let pos;
      while ((pos = stdoutBuffer.indexOf("\n")) >= 0) {
        const line = stdoutBuffer.substring(0, pos).trim();
        stdoutBuffer = stdoutBuffer.substring(pos + 1);
        if (line) {
          try {
            const parsed = JSON.parse(line);
            if (parsed.type === "done") {
              if (win && !win.isDestroyed()) {
                win.webContents.send("jarvis-stream-done", { exitCode: 0 });
              }
            } else if (parsed.type === "info") {
              console.log("Daemon info:", parsed.content);
              // Route info logs to Debug Console
              const prefixedInfo = `[DEBUG] ${parsed.content}`;
              if (win && !win.isDestroyed()) {
                win.webContents.send("terminal-log", { text: prefixedInfo, type: "stdout" });
              }
            } else if (parsed.type === "tool_call" || parsed.type === "tool_result" || parsed.type === "debug") {
              // Route tool execution traces to Debug Console
              const prefixedTool = `[DEBUG] ${JSON.stringify(parsed)}`;
              if (win && !win.isDestroyed()) {
                win.webContents.send("terminal-log", { text: prefixedTool, type: "stdout" });
              }
              if (win && !win.isDestroyed()) {
                win.webContents.send("jarvis-stream-event", parsed);
              }
            } else {
              if (win && !win.isDestroyed()) {
                win.webContents.send("jarvis-stream-event", parsed);
              }
            }
          } catch (e) {
            // Route raw logs (non-JSON) to Debug Console if they look like backend logs
            if (line.includes("HuggingFace") || line.includes("embedding") || line.includes("FAISS") || 
                line.includes("langchain") || line.includes("LangGraph") || line.includes("orchestrator") ||
                line.includes("tool") || line.includes("Warning")) {
              const prefixedRaw = `[DEBUG] ${line}`;
              if (win && !win.isDestroyed()) {
                win.webContents.send("terminal-log", { text: prefixedRaw, type: "stdout" });
              }
            }
            if (win && !win.isDestroyed()) {
              win.webContents.send("jarvis-stream-event", { type: "raw_log", content: line });
            }
          }
        }
      }
    });

    pythonDaemon.stderr.on("data", (data) => {
      const errStr = data.toString();
      // Prefix with [DEBUG] for routing to Debug Console
      const prefixedErr = `[DEBUG] ${errStr}`;
      if (win && !win.isDestroyed()) {
        win.webContents.send("terminal-log", { text: prefixedErr, type: "stderr" });
      }
      if (!errStr.includes("Warning") && !errStr.includes("UserWarning") && !errStr.includes("DeprecationWarning")) {
        console.error("Python daemon stderr:", errStr);
      }
    });

    pythonDaemon.on("close", (code) => {
      console.log(`Python daemon exited with code ${code}`);
      pythonDaemon = null;
    });
  }
  return pythonDaemon;
}

// IPC handler for Jarvis Brain
ipcMain.handle("ask-jarvis", async (event, prompt) => {
  return new Promise((resolve) => {
    const win = BrowserWindow.getAllWindows()[0];
    const daemon = getDaemonInstance(win);
    
    let fullReply = "";
    const onEvent = (_event, val) => {
      if (val.type === "final_chunk") {
        fullReply += val.content;
      }
    };
    const onDone = () => {
      ipcMain.removeListener("jarvis-stream-event", onEvent);
      ipcMain.removeListener("jarvis-stream-done", onDone);
      resolve(fullReply || "Task complete.");
    };

    ipcMain.on("jarvis-stream-event", onEvent);
    ipcMain.on("jarvis-stream-done", onDone);

    const payload = JSON.stringify({ prompt, history: [] });
    daemon.stdin.write(payload + "\n");
  });
});

ipcMain.handle("ask-jarvis-stream", (event, { prompt, history }) => {
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) return { status: "error" };

  const daemon = getDaemonInstance(win);
  const payload = JSON.stringify({ prompt, history });
  daemon.stdin.write(payload + "\n");

  return { status: "started" };
});

// Native Node Settings & Config Handlers
ipcMain.handle("get-config", async () => {
  return readConfig();
});

ipcMain.handle("save-config", async (event, newConfig) => {
  try {
    const current = readConfig();
    const updated = { ...current, ...newConfig };
    fs.writeFileSync(configPath, JSON.stringify(updated, null, 4), "utf-8");
    return { success: true, config: updated };
  } catch (e) {
    console.error("save-config error:", e);
    return { success: false, error: e.message };
  }
});

ipcMain.handle("fetch-models", async (event, { baseUrl, apiKey }) => {
  try {
    if (!baseUrl) {
      return { success: false, models: [], error: "No base URL provided" };
    }
    const targetUrl = `${baseUrl.replace(/\/+$/, "")}/models`;
    const headers = {};
    if (apiKey) {
      headers["Authorization"] = `Bearer ${apiKey}`;
    }

    const response = await fetch(targetUrl, { headers, signal: AbortSignal.timeout(8000) });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    let rawModels = [];
    if (data && Array.isArray(data.data)) {
      rawModels = data.data.map((item) => (typeof item === "object" && item.id ? item.id : item));
    } else if (Array.isArray(data)) {
      rawModels = data.map((item) => (typeof item === "object" && item.id ? item.id : item));
    }

    const models = Array.from(new Set(rawModels.filter((m) => typeof m === "string"))).sort();
    return { success: true, models };
  } catch (e) {
    console.error("fetch-models error:", e);
    return { success: false, models: [], error: e.message };
  }
});


// Vault sync and directory selectors
let syncProcess = null;
ipcMain.handle('select-directory', async (event, defaultPath) => {
  const { dialog, BrowserWindow } = require('electron');
  const win = BrowserWindow.getAllWindows()[0];
  const result = await dialog.showOpenDialog(win, {
    properties: ['openDirectory'],
    defaultPath: defaultPath || ''
  });
  if (!result.canceled && result.filePaths.length) {
    return result.filePaths[0];
  }
  return null;
});

ipcMain.handle('start-vault-sync', () => {
  if (syncProcess) return { status: 'already_running' };
  const pythonPath = "C:\\Users\\eviot\\AppData\\Local\\Programs\\Python\\Python312\\python.exe";
  syncProcess = spawn(pythonPath, ['core/ingest_knowledge.py'], {
    cwd: 'D:/Jarvis_QS',
    env: { ...process.env, PYTHONUNBUFFERED: '1' }
  });
  const { BrowserWindow } = require('electron');
  const win = BrowserWindow.getAllWindows()[0];
  if (win) {
    syncProcess.stdout.on('data', (data) => {
      const logStr = data.toString();
      // Prefix with [OUTPUT] for routing to Output panel
      const prefixedLog = `[OUTPUT] ${logStr}`;
      win.webContents.send('terminal-log', { text: prefixedLog, type: 'stdout' });
      win.webContents.send('sync-log', logStr);
    });
    syncProcess.stderr.on('data', (data) => {
      const errStr = data.toString();
      // Prefix with [DEBUG] for routing to Debug Console
      const prefixedErr = `[DEBUG] ${errStr}`;
      win.webContents.send('terminal-log', { text: prefixedErr, type: 'stderr' });
      win.webContents.send('sync-log', `[ERROR] ${errStr}`);
    });
    syncProcess.on('close', (code) => {
      syncProcess = null;
      win.webContents.send('sync-complete', { exitCode: code });
    });
  } else {
    syncProcess.on('close', () => {
      syncProcess = null;
    });
  }
  return { status: 'started' };
});

ipcMain.handle('get-vault-stats', async () => {
  const trackerPath = 'D:/Jarvis_QS/ingested_files.json';
  if (fs.existsSync(trackerPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(trackerPath, 'utf8'));
      const fileCount = Object.keys(data).length;
      const stats = fs.statSync(trackerPath);
      return { fileCount, lastSynced: stats.mtime.toLocaleString() };
    } catch (e) {
      return { fileCount: 0, lastSynced: 'Never' };
    }
  }
  return { fileCount: 0, lastSynced: 'Never' };
});


// ── Interactive Terminal & File Operations ───────────────────────────────────

const terminalProcesses = {};

function spawnTerminalProcess(id, shellPath) {
  if (terminalProcesses[id]) {
    try { terminalProcesses[id].kill(); } catch (e) {}
  }

  const shell = shellPath || "powershell.exe";
  console.log(`Spawning real PTY terminal ${id} with shell: ${shell}`);

  const ptyProcess = pty.spawn(shell, [], {
    name: "xterm-color",
    cols: 80,
    rows: 24,
    cwd: __dirname,
    env: process.env
  });

  terminalProcesses[id] = ptyProcess;

  ptyProcess.onData((data) => {
    sendToRenderer("terminal-log", { text: data, type: "stdout", terminalId: id });
  });

  ptyProcess.onExit(({ exitCode, signal }) => {
    sendToRenderer("terminal-log", { text: `\r\nProcess exited with code ${exitCode}\r\n`, type: "info", terminalId: id });
    if (terminalProcesses[id] === ptyProcess) {
      delete terminalProcesses[id];
    }
  });
}

function sendToRenderer(channel, data) {
  const win = BrowserWindow.getAllWindows()[0];
  if (win && !win.isDestroyed()) {
    win.webContents.send(channel, data);
  }
}

ipcMain.handle("create-terminal", (event, { id, shell }) => {
  spawnTerminalProcess(id, shell);
  return { success: true };
});

ipcMain.handle("write-terminal", (event, { id, text }) => {
  const proc = terminalProcesses[id];
  if (proc) {
    proc.write(text);
    return { success: true };
  }
  return { success: false };
});

ipcMain.handle("resize-terminal", (event, { id, cols, rows }) => {
  const proc = terminalProcesses[id];
  if (proc) {
    try {
      proc.resize(cols, rows);
      return { success: true };
    } catch (e) {
      console.error(`Error resizing terminal ${id}:`, e);
    }
  }
  return { success: false };
});

ipcMain.handle("kill-terminal", (event, { id }) => {
  const proc = terminalProcesses[id];
  if (proc) {
    try { proc.kill(); } catch (e) {}
    delete terminalProcesses[id];
    return { success: true };
  }
  return { success: false };
});

ipcMain.handle("get-workspace-files", async () => {
  const rootDir = "D:\\Jarvis_QS";
  
  function scanDir(dir) {
    const list = [];
    const files = fs.readdirSync(dir);
    for (const f of files) {
      if (f === "node_modules" || f === ".git" || f === ".venv" || f === "__pycache__" || f === ".pytest_cache" || f === "faiss_data") continue;
      const fullPath = path.join(dir, f);
      const relativePath = path.relative(rootDir, fullPath);
      const stat = fs.statSync(fullPath);
      if (stat.isDirectory()) {
        list.push({
          name: f,
          path: relativePath,
          isDirectory: true,
          children: scanDir(fullPath)
        });
      } else {
        list.push({
          name: f,
          path: relativePath,
          isDirectory: false
        });
      }
    }
    return list.sort((a, b) => {
      if (a.isDirectory && !b.isDirectory) return -1;
      if (!a.isDirectory && b.isDirectory) return 1;
      return a.name.localeCompare(b.name);
    });
  }

  try {
    return { success: true, files: scanDir(rootDir) };
  } catch (e) {
    return { success: false, error: e.message };
  }
});

ipcMain.handle("read-file-content", async (event, filepath) => {
  try {
    const resolvedPath = path.isAbsolute(filepath) ? filepath : path.join("D:\\Jarvis_QS", filepath);
    if (fs.existsSync(resolvedPath)) {
      const content = fs.readFileSync(resolvedPath, "utf-8");
      return { success: true, content };
    } else {
      return { success: false, error: "File not found." };
    }
  } catch (e) {
    return { success: false, error: e.message };
  }
});

app.on("will-quit", () => {
  if (pythonDaemon) {
    try { pythonDaemon.kill(); } catch (e) {}
    pythonDaemon = null;
  }
  for (const id in terminalProcesses) {
    try { terminalProcesses[id].kill(); } catch(e){}
  }
});
