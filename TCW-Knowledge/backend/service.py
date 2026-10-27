import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import psutil
from qdrant_client import QdrantClient, models
from backend.config import AppError, ROOT, load_config
from backend.inference import Ollama
from ingestion.extract import extract, chunk, EXTRACTION_VERSION
from retrieval.grounding import UNKNOWN, SCHEMA, prepare_prompt, validate_answer

def now():
    return datetime.now(timezone.utc).isoformat()

def filehash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Service:
    def __init__(self, root=ROOT, inference=None):
        self.root = Path(root)
        self.c = load_config(root)
        for p in ("data/index", "data/vault", "data/uploads", "logs"):
            (self.root / p).mkdir(parents=True, exist_ok=True)
        self.dbpath = self.root / "data/index/metadata.sqlite"
        self.lock = threading.Lock()
        self.operation = None
        self.inference = inference or Ollama(self.c)
        self.q = QdrantClient(path=str(self.root / "data/index/qdrant"), force_disable_check_same_thread=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS documents(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, current_revision TEXT, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions(
              id TEXT PRIMARY KEY, document_id TEXT, file_hash TEXT, vault_path TEXT,
              indexed_at TEXT, fingerprint TEXT, collection TEXT, metadata TEXT, chunk_count INTEGER);
            CREATE TABLE IF NOT EXISTS chunks(
              id TEXT PRIMARY KEY, revision_id TEXT, ordinal INTEGER, text TEXT,
              page_number INTEGER, section TEXT, char_start INTEGER, char_end INTEGER);
            CREATE INDEX IF NOT EXISTS chunks_revision ON chunks(revision_id);
            CREATE TABLE IF NOT EXISTS metrics(id TEXT PRIMARY KEY, created_at TEXT, result TEXT);
            """)
        self.log("startup", runtime="local", extraction_version=EXTRACTION_VERSION)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.dbpath, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def busy(self, name):
        if not self.lock.acquire(blocking=False):
            raise AppError("The workstation is processing another request. Try again shortly.", 409, "busy")
        self.operation = {"name": name, "started_at": now()}
        try:
            yield
        finally:
            self.operation = None
            self.lock.release()

    def log(self, event, **fields):
        # Deliberately exclude question text, excerpts, prompts, and model output.
        with (self.root / "logs/events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": now(), "event": event, **fields}) + "\n")

    def manifest(self):
        p = self.root / "data/corpus_manifest.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"documents": []}

    def corpus(self):
        result = []
        indexed = {d["document_id"]: d for d in self.documents()}
        for raw in self.manifest()["documents"]:
            d = dict(raw)
            live = indexed.get(d["document_id"])
            d["index_state"] = "active" if live and live["active"] else "not_indexed"
            d["chunk_count"] = live["chunk_count"] if live else 0
            result.append(d)
        return result

    def documents(self):
        with self.db() as db:
            rows = db.execute("""SELECT d.*, r.file_hash, r.indexed_at, r.chunk_count, r.metadata,
                r.fingerprint FROM documents d JOIN revisions r ON r.id=d.current_revision
                ORDER BY d.title""").fetchall()
        return [{**json.loads(r["metadata"]), "document_id": r["id"], "active": bool(r["active"]),
                 "revision_id": r["current_revision"], "file_hash": r["file_hash"],
                 "indexed_at": r["indexed_at"], "chunk_count": r["chunk_count"],
                 "embedding_fingerprint": r["fingerprint"]} for r in rows]

    def import_corpus(self, document_id):
        record = next((d for d in self.manifest()["documents"] if d["document_id"] == document_id), None)
        if not record or not record.get("demo_eligible") or not record.get("file_path"):
            raise AppError("This source is unavailable or excluded from the demonstration.", 400, "source_excluded")
        p = (self.root / record["file_path"]).resolve()
        if not p.is_relative_to(self.root.resolve() / "data"):
            raise AppError("Invalid source path.", 400, "invalid_path")
        return self.index(p, record)

    def index(self, path, metadata, force=False):
        with self.busy("indexing"):
            return self._index(path, metadata, force)

    def _index(self, path, metadata, force=False):
        started = time.perf_counter()
        metadata = dict(metadata)
        doc_id = metadata.get("document_id") or "upload-" + str(uuid.uuid4())
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", doc_id):
            raise AppError("Invalid document identifier.", 400, "invalid_id")
        if not metadata.get("demo_eligible") or metadata.get("status") in {"excluded", "draft", "superseded"}:
            raise AppError("Document is not cleared for this demonstration.", 400, "source_excluded")
        path = Path(path)
        digest = filehash(path)
        blocks, warnings = extract(path)
        chunks = chunk(blocks, self.c["chunk_chars"], self.c["chunk_overlap"])
        if len(chunks) > 6000:
            raise AppError("Document exceeds the demo chunk limit.", 400, "too_large")
        with self.db() as db:
            duplicate = db.execute("""SELECT d.id FROM documents d JOIN revisions r
                ON r.id=d.current_revision WHERE r.file_hash=? AND d.active=1""", (digest,)).fetchone()
        if duplicate and (duplicate["id"] != doc_id or not force):
            return {"status": "unchanged" if duplicate["id"] == doc_id else "duplicate",
                    "document_id": duplicate["id"], "file_hash": digest}
        fingerprint = self.inference.embedding_identity()
        vectors = []
        for offset in range(0, len(chunks), self.c["embedding_batch_size"]):
            batch = chunks[offset:offset + self.c["embedding_batch_size"]]
            values = self.inference.embed([metadata["title"] + "\n" + c["section"] + "\n" + c["text"] for c in batch])
            vectors.extend(values)
        v = np.asarray(vectors, dtype=np.float32)
        if v.ndim != 2 or v.shape[0] != len(chunks) or not np.isfinite(v).all() or np.any(np.linalg.norm(v, axis=1) == 0):
            raise AppError("Embedding vectors were invalid.", code="invalid_embeddings")
        collection = "tcw_" + fingerprint[:24]
        if not self.q.collection_exists(collection):
            self.q.create_collection(collection, vectors_config=models.VectorParams(size=v.shape[1], distance=models.Distance.COSINE))
        revision = str(uuid.uuid4())
        ids = [str(uuid.uuid5(uuid.UUID(revision), str(c["ordinal"]))) for c in chunks]
        vault_rel = f"data/vault/{digest}{path.suffix.lower()}"
        vault = self.root / vault_rel
        if not vault.exists():
            shutil.copyfile(path, vault)
        metadata.update(document_id=doc_id, filename=metadata.get("filename") or path.name,
                        extraction_warnings=warnings, extraction_version=EXTRACTION_VERSION)
        stamp = now()
        try:
            self.q.upsert(collection, points=[
                models.PointStruct(id=cid, vector=vec.tolist(),
                                   payload={"revision_id": revision, "document_id": doc_id})
                for cid, vec in zip(ids, v)], wait=True)
            with self.db() as db:
                db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?)",
                           (revision, doc_id, digest, vault_rel, stamp, fingerprint, collection,
                            json.dumps(metadata), len(chunks)))
                db.executemany("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)", [
                    (cid, revision, c["ordinal"], c["text"], c["page_number"], c["section"], c["char_start"], c["char_end"])
                    for cid, c in zip(ids, chunks)])
                db.execute("""INSERT INTO documents VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, current_revision=excluded.current_revision, active=1""",
                           (doc_id, metadata["title"], revision))
                # Supersession is explicit; never inferred from a filename or timestamp.
                for superseded in metadata.get("supersedes", []):
                    if superseded != doc_id:
                        db.execute("UPDATE documents SET active=0 WHERE id=?", (superseded,))
        except Exception:
            self.q.delete(collection, models.PointIdsList(points=ids), wait=True)
            raise
        seconds = time.perf_counter() - started
        self.log("indexed", document_id=doc_id, revision_id=revision, chunks=len(chunks), elapsed_s=seconds)
        return {"status": "indexed", "document_id": doc_id, "revision_id": revision,
                "chunk_count": len(chunks), "file_hash": digest, "elapsed_s": seconds, "warnings": warnings}

    def revision(self, doc_id):
        with self.db() as db:
            r = db.execute("""SELECT r.*, d.active FROM documents d JOIN revisions r
                ON r.id=d.current_revision WHERE d.id=?""", (doc_id,)).fetchone()
        if not r:
            raise AppError("Document not found.", 404, "not_found")
        return dict(r)

    def reindex(self, doc_id):
        r = self.revision(doc_id)
        return self.index(self.root / r["vault_path"], json.loads(r["metadata"]), force=True)

    def deactivate(self, doc_id):
        with self.busy("deactivating"):
            self.revision(doc_id)
            with self.db() as db:
                db.execute("UPDATE documents SET active=0 WHERE id=?", (doc_id,))
            self.log("deactivated", document_id=doc_id)
        return {"status": "inactive", "document_id": doc_id}

    def source(self, chunk_id):
        with self.db() as db:
            r = db.execute("""SELECT c.*, r.document_id, r.metadata, r.file_hash, r.indexed_at
              FROM chunks c JOIN revisions r ON c.revision_id=r.id
              JOIN documents d ON d.current_revision=r.id
              WHERE c.id=? AND d.active=1""", (chunk_id,)).fetchone()
        if not r:
            raise AppError("Source is no longer active; rerun the question.", 404, "inactive_source")
        return {**json.loads(r["metadata"]), **{k: r[k] for k in r.keys() if k != "metadata"},
                "original_url": f"/api/documents/{r['document_id']}/original",
                "preview_url": f"/source/{r['id']}"}

    def _search(self, question):
        start = time.perf_counter()
        with self.db() as db:
            active = db.execute("""SELECT r.id, r.fingerprint, r.collection FROM revisions r
                JOIN documents d ON d.current_revision=r.id WHERE d.active=1""").fetchall()
        if not active:
            raise AppError("No approved documents are currently indexed.", 409, "empty_index")
        identity = self.inference.embedding_identity()
        if any(r["fingerprint"] != identity for r in active):
            raise AppError("The embedding model or prefixes changed. Rebuild the entire active index.", 409, "index_model_mismatch")
        embed_start = time.perf_counter()
        vector = self.inference.embed([question], query=True)[0]
        embedding_s = time.perf_counter() - embed_start
        search_start = time.perf_counter()
        try:
            points = self.q.query_points(
                collection_name=active[0]["collection"], query=vector,
                query_filter=models.Filter(must=[models.FieldCondition(
                    key="revision_id", match=models.MatchAny(any=[r["id"] for r in active]))]),
                limit=self.c["candidate_count"], with_payload=True).points
        except Exception as exc:
            raise AppError("Knowledge base search service is unavailable.", code="vector_unavailable") from exc
        vector_s = time.perf_counter() - search_start
        candidates = []
        for p in points:
            s = self.source(str(p.id))
            s["score"] = float(p.score)
            candidates.append(s)
        selected, per_doc, chars = [], {}, 0
        for s in candidates:
            n = per_doc.get(s["document_id"], 0)
            if s["score"] < self.c["min_cosine_score"] or n >= 3:
                continue
            cost = len(s["text"]) + len(s["title"]) + 650
            if chars + cost > self.c["context_char_budget"]:
                continue
            s = dict(s, source_id=f"S{len(selected) + 1}", chunk_id=s["id"])
            selected.append(s)
            per_doc[s["document_id"]] = n + 1
            chars += cost
            if len(selected) >= self.c["context_chunk_count"]:
                break
        return selected, candidates, {"retrieval_s": time.perf_counter() - start,
            "query_embedding_s": embedding_s, "vector_search_s": vector_s,
            "reranking_s": None, "reranker": "not implemented"}

    def search(self, question):
        with self.busy("retrieving"):
            evidence, candidates, metrics = self._search(question)
            return {"evidence": evidence, "candidates": candidates, "metrics": metrics,
                    "score_note": "Actual cosine similarity; not an answer-confidence probability."}

    def ask(self, question, diagnostics=False):
        started = time.perf_counter()
        request_id = str(uuid.uuid4())
        with self.busy("answering"):
            evidence, candidates, metrics = self._search(question)
            if not evidence:
                answer = {"status": "unknown", "answer": UNKNOWN, "claims": [], "citations": []}
                messages = []
                metrics.update(model=None, time_to_first_content_token_s=None,
                               generation_wall_s=0, tokens_generated=0, tokens_per_second=None)
            else:
                model = self.inference.model_info(self.c["generation_model"])
                prep = time.perf_counter()
                messages = prepare_prompt(question, evidence)
                metrics["prompt_preparation_s"] = time.perf_counter() - prep
                raw, generated = self.inference.generate(messages, SCHEMA)
                metrics.update(generated, model_digest=model["digest"], quantization=model.get("quantization"))
                try:
                    answer = validate_answer(raw, evidence)
                except AppError as exc:
                    self.log("grounding_rejected", request_id=request_id, code=exc.code)
                    raise
            metrics.update(total_s=time.perf_counter() - started, request_id=request_id,
                           context_tokens=self.c["context_tokens"])
            result = {**answer, "metrics": metrics, "retrieved_evidence": evidence,
                      "grounding_note": "Citations and exact excerpts are checked. Claim correctness still requires review."}
            if diagnostics and self.c["diagnostics_enabled"]:
                result["diagnostics"] = {"question": question, "candidates": candidates,
                    "final_messages": messages, "reranking": "Not implemented",
                    "cosine_threshold": self.c["min_cosine_score"]}
            with self.db() as db:
                db.execute("INSERT INTO metrics VALUES(?,?,?)", (request_id, now(), json.dumps(metrics)))
            self.log("query_completed", **metrics, answer_status=answer["status"])
            return result

    def rebuild(self):
        with self.busy("rebuilding"):
            old = self.documents()
            done = []
            try:
                for d in old:
                    if d["active"]:
                        r = self.revision(d["document_id"])
                        done.append(self._index(self.root / r["vault_path"], json.loads(r["metadata"]), True))
            except Exception:
                # Restore all previous active revision pointers; old vectors are retained.
                with self.db() as db:
                    for d in old:
                        db.execute("UPDATE documents SET current_revision=?,active=? WHERE id=?",
                                   (d["revision_id"], int(d["active"]), d["document_id"]))
                raise
            return {"status": "rebuilt", "documents": done}

    def metrics(self):
        with self.db() as db:
            return [dict(created_at=r["created_at"], **json.loads(r["result"])) for r in db.execute(
                "SELECT * FROM metrics ORDER BY created_at DESC LIMIT 50")]

    def set_generation_model(self, name):
        if "cloud" in name.lower() or "://" in name:
            raise AppError("Select an installed local model.", 400, "remote_model")
        with self.busy("changing_model"):
            detail = self.inference.model_info(name)
            if "completion" not in detail.get("capabilities", []):
                raise AppError("Selected model does not report text-generation capability.", 400, "not_generator")
            path = self.root / "config/settings.json"
            path.parent.mkdir(exist_ok=True)
            temporary = path.with_suffix(".tmp")
            updated = {**self.c, "generation_model": name}
            temporary.write_text(json.dumps(updated, indent=2), encoding="utf-8")
            temporary.replace(path)
            self.c["generation_model"] = name
            self.log("generation_model_changed", model=name, digest=detail["digest"])
        return {"status": "model_selected", "model": name, "details": detail}

    def status(self):
        mem = psutil.virtual_memory()
        try:
            process_ram = psutil.Process().memory_info().rss / 1024**2
        except (psutil.Error, OSError):
            process_ram = None
        gpus = []
        gpu_error = None
        try:
            cmd = ["nvidia-smi", "--query-gpu=uuid,name,memory.total,memory.used,utilization.gpu",
                   "--format=csv,noheader,nounits"]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
            if p.returncode:
                gpu_error = "nvidia-smi returned an error."
            else:
                for row in csv.reader(io.StringIO(p.stdout)):
                    gpus.append(dict(zip(["uuid", "name", "vram_total_mib", "vram_used_mib", "utilization_percent"], [x.strip() for x in row])))
        except (OSError, subprocess.TimeoutExpired):
            gpu_error = "NVIDIA telemetry unavailable in this runtime."
        docs = self.documents()
        ollama = self.inference.status()
        collection_ok = True
        try:
            self.q.get_collections()
        except Exception:
            collection_ok = False
        installed = {x["name"] for x in ollama["installed"] if not x.get("remote")}
        required = [self.c[k] if ":" in self.c[k] else self.c[k] + ":latest"
                    for k in ("generation_model", "embedding_model")]
        missing = [n for n in required if n not in installed]
        return {"timestamp": now(), "runtime_platform": os.name, "audience": "single workstation / management demo",
            "document_count": sum(d["active"] for d in docs),
            "chunk_count": sum(d["chunk_count"] for d in docs if d["active"]),
            "ollama": ollama, "missing_models": missing, "vector_db_available": collection_ok,
            "vector_db": "Qdrant persistent local mode", "operation": self.operation,
            "generation_model": self.c["generation_model"], "embedding_model": self.c["embedding_model"],
            "context_tokens": self.c["context_tokens"], "diagnostics_enabled": self.c["diagnostics_enabled"],
            "cpu_percent": psutil.cpu_percent(interval=None), "ram_total_gib": mem.total / 1024**3,
            "ram_used_gib": mem.used / 1024**3, "process_ram_mib": process_ram,
            "gpus": gpus, "gpu_telemetry_note": gpu_error,
            "ready_for_query": bool(ollama["available"] and not missing and any(d["active"] for d in docs) and collection_ok),
            "authentication": "Loopback-only demo; AD and per-user role filtering not implemented.",
            "model_assignment_note": "GPU selection belongs to the Ollama process. Telemetry lists observed GPUs, not per-query attribution."}

    def close(self):
        self.q.close()
        if hasattr(self.inference, "http"):
            self.inference.http.close()
