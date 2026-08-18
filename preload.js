const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  // Window Controls
  minimize: () => ipcRenderer.send("window-minimize"),
  maximize: () => ipcRenderer.send("window-maximize"),
  close: () => ipcRenderer.send("window-close"),

  // Jarvis AI Brain
  askJarvis: (prompt) => ipcRenderer.invoke("ask-jarvis", prompt),
  askJarvisStream: (prompt) => ipcRenderer.invoke("ask-jarvis-stream", prompt),
  onJarvisStreamEvent: (callback) => {
    // Clear existing listeners to prevent leaks
    ipcRenderer.removeAllListeners("jarvis-stream-event");
    ipcRenderer.on("jarvis-stream-event", (_event, val) => callback(val));
  },
  onJarvisStreamDone: (callback) => {
    ipcRenderer.removeAllListeners("jarvis-stream-done");
    ipcRenderer.on("jarvis-stream-done", (_event, val) => callback(val));
  },

  // Dynamic Configuration & Model Management
  getConfig: () => ipcRenderer.invoke("get-config"),
  saveConfig: (config) => ipcRenderer.invoke("save-config", config),
  fetchModels: (baseUrl, apiKey) => ipcRenderer.invoke("fetch-models", { baseUrl, apiKey }),

  // Knowledge Vault Controls
  selectDirectory: (defaultPath) => ipcRenderer.invoke("select-directory", defaultPath || ""),
  startVaultSync: () => ipcRenderer.invoke("start-vault-sync"),
  getVaultStats: () => ipcRenderer.invoke("get-vault-stats"),
  onSyncLog: (callback) => ipcRenderer.on("sync-log", (_event, value) => callback(value)),
  onSyncComplete: (callback) => ipcRenderer.on("sync-complete", (_event, value) => callback(value)),
  onTerminalLog: (callback) => {
    ipcRenderer.removeAllListeners("terminal-log");
    ipcRenderer.on("terminal-log", (_event, data) => callback(data));
  },

  // Legacy Settings compatibility
  getSettings: () => ipcRenderer.invoke("get-settings"),
  saveSettings: (value) => ipcRenderer.invoke("save-settings", value),

  // Interactive Terminal & File Operations
  createTerminal: (id, shell) => ipcRenderer.invoke("create-terminal", { id, shell }),
  writeTerminal: (payloadOrId, text) => {
    if (text !== undefined) {
      return ipcRenderer.invoke("write-terminal", { id: payloadOrId, text });
    }
    return ipcRenderer.invoke("write-terminal", payloadOrId);
  },
  killTerminal: (id) => ipcRenderer.invoke("kill-terminal", { id }),
  resizeTerminal: (id, cols, rows) => ipcRenderer.invoke("resize-terminal", { id, cols, rows }),
  getWorkspaceFiles: () => ipcRenderer.invoke("get-workspace-files"),
  readFileContent: (filepath) => ipcRenderer.invoke("read-file-content", filepath),
});
