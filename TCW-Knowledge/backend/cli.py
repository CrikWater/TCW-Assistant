"""Administrative CLI: mutations use the running app; backups require it stopped."""
import argparse
import hashlib
import json
import os
import platform
import sys
import time
import zipfile
from datetime import datetime, timezone
import httpx
from backend.config import ROOT, load_config
from ingestion.extract import extract, chunk

def connection():
    c = load_config()
    return httpx.Client(base_url=f"http://127.0.0.1:{c['port']}", timeout=3600, trust_env=False)

def call(client, method, endpoint, body=None):
    headers = {}
    if method != "GET":
        token = ROOT / "logs/session-token"
        if not token.exists():
            raise RuntimeError("Start the application first.")
        headers["X-TCW-Token"] = token.read_text(encoding="utf-8").strip()
    r = client.request(method, endpoint, headers=headers, json=body)
    r.raise_for_status()
    return r.json()

def extraction_audit():
    manifest_path = ROOT / "data/corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for d in manifest["documents"]:
        if not d.get("file_path") or not d.get("demo_eligible"):
            continue
        path = ROOT / d["file_path"]
        t = time.perf_counter()
        blocks, warnings = extract(path)
        pieces = chunk(blocks)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        d["file_hash"] = digest
        rows.append({"document_id": d["document_id"], "filename": d["filename"], "status": d["status"],
            "sha256": digest, "size_bytes": path.stat().st_size,
            "extracted_characters": sum(len(b.text) for b in blocks), "prepared_chunks": len(pieces),
            "physical_pages_with_text": len({b.page for b in blocks if b.page}),
            "elapsed_s": time.perf_counter() - t, "warnings": warnings,
            "embedding_status": "not_tested_by_extraction_audit"})
    result = {"executed_at": datetime.now(timezone.utc).isoformat(), "runtime": platform.platform(),
        "purpose": "Real-source extraction and chunking. Prepared chunks are NOT an embedded/searchable index.",
        "documents": rows}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output = ROOT / "evidence/extraction_audit.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

def backup():
    with connection() as client:
        try:
            client.get("/api/status", timeout=2).raise_for_status()
        except httpx.HTTPError:
            pass
        else:
            raise RuntimeError("Stop the TCW application before making a consistent offline backup.")
    from qdrant_client import QdrantClient
    lock_probe = QdrantClient(path=str(ROOT / "data/index/qdrant"))
    lock_probe.close()
    name = "TCW_Knowledge_Backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
    folder = ROOT / "backups"; folder.mkdir(exist_ok=True)
    path = folder / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for base in [ROOT / "data", ROOT / "config"]:
            for f in base.rglob("*"):
                if f.is_file() and f.name != ".lock" and "uploads" not in f.parts:
                    z.write(f, f.relative_to(ROOT))
    return {"status": "backup_created", "path": str(path)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "status", "index", "reindex", "rebuild", "audit", "backup"])
    parser.add_argument("--document-id")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        c = load_config()
        (ROOT / "logs").mkdir(exist_ok=True)
        pidfile = ROOT / "logs/app-process.json"
        pidfile.write_text(json.dumps({"pid": os.getpid(), "root": str(ROOT), "executable": sys.executable}), encoding="utf-8")
        try:
            from backend.app import app
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=c["port"], proxy_headers=False, workers=1))
            app.state.shutdown_callback = lambda: setattr(server, "should_exit", True)
            server.run()
        finally:
            pidfile.unlink(missing_ok=True)
        return
    if args.command == "audit":
        result = extraction_audit()
    elif args.command == "backup":
        result = backup()
    else:
        with connection() as client:
            if args.command == "status":
                result = call(client, "GET", "/api/status")
            elif args.command == "index":
                corpus = call(client, "GET", "/api/corpus")
                selected = [d for d in corpus if d.get("demo_eligible") and (
                    d["document_id"] == args.document_id if args.document_id else d["status"] == "active")]
                if not selected:
                    raise RuntimeError("No matching eligible corpus sources.")
                result = []
                for d in selected:
                    print("Indexing:", d["title"], flush=True)
                    result.append(call(client, "POST", f"/api/corpus/{d['document_id']}/import", {}))
            elif args.command == "reindex":
                if not args.document_id:
                    raise RuntimeError("--document-id is required.")
                result = call(client, "POST", f"/api/documents/{args.document_id}/reindex", {})
            else:
                result = call(client, "POST", "/api/rebuild", {})
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
