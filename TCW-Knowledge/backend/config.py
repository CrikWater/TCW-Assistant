import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

def load_config(root=ROOT):
    root = Path(root)
    default = ROOT / "config/settings.example.json"
    data = json.loads(default.read_text(encoding="utf-8"))
    custom = root / "config/settings.json"
    if custom.exists():
        data.update(json.loads(custom.read_text(encoding="utf-8-sig")))
    u = urlsplit(data["ollama_url"])
    if (u.scheme != "http" or u.hostname not in {"127.0.0.1", "localhost", "::1"}
        or u.username or u.password or u.query or u.fragment or u.path not in {"", "/"}):
        raise ValueError("This demo permits only a loopback HTTP Ollama endpoint.")
    for key in ["generation_model", "embedding_model"]:
        if "cloud" in data[key].lower() or "://" in data[key]:
            raise ValueError("Cloud models are not allowed.")
    if not 512 <= data["chunk_chars"] <= 4000:
        raise ValueError("chunk_chars must be 512..4000.")
    if not 0 <= data["chunk_overlap"] < data["chunk_chars"] // 2:
        raise ValueError("Invalid chunk overlap.")
    if not 1 <= data["embedding_batch_size"] <= 32:
        raise ValueError("Invalid embedding batch size.")
    if not 0 <= data["min_cosine_score"] <= 1:
        raise ValueError("Invalid cosine threshold.")
    return data

class AppError(Exception):
    def __init__(self, message, status=503, code="unavailable"):
        super().__init__(message)
        self.status = status
        self.code = code
