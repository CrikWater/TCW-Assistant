"""Only the local Ollama transport is implemented. No cloud fallback."""
import json
import time
import hashlib
from typing import Protocol
import httpx
from backend.config import AppError

class InferenceBackend(Protocol):
    def model_info(self, name: str) -> dict: ...
    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...
    def generate(self, messages: list[dict], schema: dict) -> tuple[dict, dict]: ...

class Ollama:
    def __init__(self, config):
        self.c = config
        self.http = httpx.Client(base_url=config["ollama_url"].rstrip("/"),
                                 timeout=config["request_timeout_seconds"],
                                 trust_env=False, follow_redirects=False)

    def request(self, method, endpoint, **kwargs):
        try:
            r = self.http.request(method, endpoint, **kwargs)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("Local language model service is unavailable or rejected the request. Check Ollama and installed models.", code="ollama_unavailable") from exc

    def model_info(self, name):
        models = self.request("GET", "/api/tags").get("models", [])
        canonical = name if ":" in name else name + ":latest"
        found = next((m for m in models if m.get("name") == canonical or m.get("model") == canonical), None)
        if not found:
            raise AppError(f"Required local model is not installed: {name}", code="model_missing")
        detail = self.request("POST", "/api/show", json={"model": name})
        if any(found.get(k) or detail.get(k) for k in ("remote_host", "remote_model")):
            raise AppError("Remote/cloud-backed Ollama models are prohibited.", 400, "remote_model")
        if not found.get("digest"):
            raise AppError("Ollama did not provide an installed model digest.", code="model_identity_missing")
        return {"name": canonical, "digest": found["digest"], "size_bytes": found.get("size"),
                "quantization": found.get("details", {}).get("quantization_level"),
                "family": found.get("details", {}).get("family"), "capabilities": detail.get("capabilities", [])}

    def embedding_identity(self):
        info = self.model_info(self.c["embedding_model"])
        info.update(document_prefix=self.c["embedding_document_prefix"], query_prefix=self.c["embedding_query_prefix"])
        return hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()

    def embed(self, texts, query=False):
        prefix = self.c["embedding_query_prefix" if query else "embedding_document_prefix"]
        result = self.request("POST", "/api/embed", json={
            "model": self.c["embedding_model"], "input": [prefix + t for t in texts],
            "truncate": False, "keep_alive": self.c["keep_alive"],
        })
        values = result.get("embeddings", [])
        if len(values) != len(texts) or not values:
            raise AppError("Embedding output count did not match the input.", code="invalid_embeddings")
        return values

    def generate(self, messages, schema):
        start = time.perf_counter()
        first, content, final = None, "", {}
        payload = {
            "model": self.c["generation_model"], "messages": messages,
            "stream": True, "format": schema, "keep_alive": self.c["keep_alive"],
            "options": {"temperature": self.c["temperature"], "num_ctx": self.c["context_tokens"],
                        "num_predict": self.c["output_tokens"], "num_thread": self.c["num_thread"]}}
        if self.c.get("generation_thinking") is not None:
            detail = self.model_info(self.c["generation_model"])
            if "thinking" in detail["capabilities"]:
                payload["think"] = self.c["generation_thinking"]
        try:
            with self.http.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    part = json.loads(line)
                    if part.get("error"):
                        raise AppError("Local generation failed.", code="generation_failed")
                    token = part.get("message", {}).get("content", "")
                    if token and first is None:
                        first = time.perf_counter() - start
                    content += token
                    if part.get("done"):
                        final = part
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("Local generation failed or timed out. No answer was substituted.", code="generation_failed") from exc
        if not final or final.get("done_reason") == "length":
            raise AppError("Local generation was incomplete; reduce context or increase output_tokens.", code="generation_incomplete")
        duration = final.get("eval_duration", 0) / 1e9
        metrics = {"model": self.c["generation_model"], "time_to_first_content_token_s": first,
                   "generation_wall_s": time.perf_counter() - start,
                   "eval_duration_s": duration, "tokens_generated": final.get("eval_count"),
                   "tokens_per_second": final.get("eval_count", 0) / duration if duration else None,
                   "prompt_tokens": final.get("prompt_eval_count"), "load_duration_s": final.get("load_duration", 0) / 1e9}
        try:
            return json.loads(content), metrics
        except ValueError as exc:
            raise AppError("Model returned invalid structured output. No answer was displayed.", code="invalid_output") from exc

    def status(self):
        try:
            tags = self.request("GET", "/api/tags", timeout=3).get("models", [])
            loaded = self.request("GET", "/api/ps", timeout=3).get("models", [])
            return {"available": True, "installed": [
                {"name": m.get("name"), "digest": m.get("digest"),
                 "quantization": m.get("details", {}).get("quantization_level"),
                 "remote": bool(m.get("remote_host") or m.get("remote_model"))} for m in tags],
                "loaded": [{"name": m.get("name"), "size_bytes": m.get("size"),
                            "vram_bytes": m.get("size_vram"), "context_length": m.get("context_length")} for m in loaded]}
        except AppError:
            return {"available": False, "installed": [], "loaded": [], "error": "Local Ollama is unavailable."}
