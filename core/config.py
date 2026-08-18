import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# System Paths
user_config_path = Path(__file__).resolve().parent.parent / "user_config.json"

def get_paths():
    inbox = "D:/knowledge_inbox"
    faiss = "D:/Jarvis_QS/faiss_data"
    if user_config_path.exists():
        try:
            import json
            with open(user_config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                inbox = cfg.get("inbox_path", inbox)
                faiss = cfg.get("faiss_path", faiss)
        except Exception:
            pass
    return inbox, faiss

INBOX_PATH, FAISS_PATH = get_paths()
DB_PATH = FAISS_PATH
# INBOX_PATH resolved dynamically above

# Primary LLM Configuration
PRIMARY_LLM_MODEL = os.getenv("PRIMARY_LLM_MODEL", "jarvis_brain")
OMNIROUTE_BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "https://omni.dhanrickeviota.com/v1")
OMNIROUTE_API_KEY = os.getenv("OMNIROUTE_API_KEY", "sk-9e731d7385077d7e-2cbf0c-598b3170")

# Fallback LLM Configuration
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "qwen2.5-coder:3b-instruct-q4_K_M")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# Embedding Configuration
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "mistral/mistral/mistral-embed")