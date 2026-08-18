import os
import sys
import json
from pathlib import Path
import requests

# Resolve to D:\Jarvis_QS\user_config.json — same file Node.js writes to
CONFIG_FILE = Path(__file__).resolve().parent.parent / "user_config.json"

DEFAULT_CONFIG = {
    "provider_type": "omniroute",
    "primary_model": "jarvis_brain",
    "fallback_model": "qwen2.5-coder:3b-instruct-q4_K_M",
    "base_url": "https://omni.dhanrickeviota.com/v1",
    "api_key": "sk-9e731d7385077d7e-2cbf0c-598b3170",
    "ollama_base_url": "http://localhost:11434/v1",
    "embedding_model": "mistral/mistral/mistral-embed",
    "embedding_base_url": "https://omni.dhanrickeviota.com/v1",
    "embedding_api_key": "sk-9e731d7385077d7e-2cbf0c-598b3170",
    "inbox_path": "D:/knowledge_inbox",
    "faiss_path": "D:/Jarvis_QS/faiss_data"
}

def load_config():
    """Loads and merges settings from user_config.json with defaults."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)

def save_config(new_config: dict) -> dict:
    """Merges new_config over current settings and writes user_config.json."""
    current = load_config()
    updated = {**current, **new_config}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=4)
    return updated

def fetch_available_models(base_url: str, api_key: str = "") -> dict:
    """
    Hits the provider's /models endpoint to auto-discover available model IDs.
    Compatible with OmniRoute, OpenAI, Anthropic, Ollama, LM Studio.
    """
    if not base_url:
        return {"success": False, "models": [], "error": "No base URL provided"}

    target_url = f"{base_url.rstrip('/')}/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(target_url, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()

        models = []
        if "data" in data and isinstance(data["data"], list):
            for item in data["data"]:
                if isinstance(item, dict) and "id" in item:
                    models.append(item["id"])
                elif isinstance(item, str):
                    models.append(item)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "id" in item:
                    models.append(item["id"])
                elif isinstance(item, str):
                    models.append(item)

        unique = sorted(set(m for m in models if isinstance(m, str)))
        return {"success": True, "models": unique}

    except Exception as e:
        return {"success": False, "models": [], "error": str(e)}


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "get"

    if cmd == "get":
        print(json.dumps(load_config()))

    elif cmd == "save" and len(sys.argv) > 2:
        try:
            new_cfg = json.loads(sys.argv[2])
            print(json.dumps(save_config(new_cfg)))
        except Exception as e:
            print(json.dumps({"success": False, "error": str(e)}))

    elif cmd == "fetch_models" and len(sys.argv) > 2:
        base = sys.argv[2]
        key = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps(fetch_available_models(base, key)))

    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
