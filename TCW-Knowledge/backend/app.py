import html
import json
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from backend.config import ROOT, AppError
from backend.service import Service
from ingestion.extract import SUPPORTED

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2500)
    diagnostics: bool = False

class ModelChoice(BaseModel):
    name: str = Field(min_length=1, max_length=200)

def create_app(service=None):
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or Service()
        app.state.root = app.state.service.root
        (app.state.root / "logs/session-token").write_text(token, encoding="utf-8")
        try:
            yield
        finally:
            if not service:
                app.state.service.close()
            (app.state.root / "logs/session-token").unlink(missing_ok=True)

    app = FastAPI(title="Tri-County Internal Knowledge Assistant", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = urlsplit("//" + request.headers.get("host", "")).hostname
        if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "Loopback host required."}, status_code=403)
        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1", "testclient"}:
            return JSONResponse({"detail": "This demo only accepts local workstation connections."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin requests are prohibited."}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(request.headers.get("x-tcw-token", ""), token):
                return JSONResponse({"detail": "Local session token required."}, status_code=403)
        if int(request.headers.get("content-length", "0")) > 32 * 1024 * 1024:
            return JSONResponse({"detail": "Upload too large."}, status_code=413)
        result = await call_next(request)
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Cache-Control"] = "no-store"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"
        return result

    @app.exception_handler(AppError)
    async def known_error(request, exc):
        request.app.state.service.log("request_failed", code=exc.code)
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=exc.status)

    @app.exception_handler(ValueError)
    async def invalid_source(request, exc):
        request.app.state.service.log("validation_failed", exception=type(exc).__name__)
        return JSONResponse({"detail": str(exc), "code": "validation_failed"}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        request.app.state.service.log("request_failed", exception=type(exc).__name__)
        return JSONResponse({"detail": "The operation failed. No success was recorded. Check local logs.",
                             "code": "internal_error"}, status_code=500)

    def svc():
        return app.state.service

    @app.get("/")
    def home():
        return FileResponse(ROOT / "frontend/index.html")

    @app.get("/api/session")
    def session():
        return {"token": token}

    @app.get("/api/status")
    def status():
        return svc().status()

    @app.get("/api/corpus")
    def corpus():
        return svc().corpus()

    @app.get("/api/documents")
    def documents():
        return svc().documents()

    @app.get("/api/metrics")
    def metrics():
        return svc().metrics()

    @app.post("/api/generation-model")
    def generation_model(choice: ModelChoice):
        return svc().set_generation_model(choice.name)

    @app.post("/api/ask")
    def ask(q: Question):
        return svc().ask(q.question, q.diagnostics)

    @app.post("/api/search")
    def search(q: Question):
        return svc().search(q.question)

    @app.post("/api/corpus/{document_id}/import")
    def import_source(document_id: str):
        return svc().import_corpus(document_id)

    @app.post("/api/documents/{document_id}/reindex")
    def reindex(document_id: str):
        return svc().reindex(document_id)

    @app.post("/api/documents/{document_id}/deactivate")
    def deactivate(document_id: str):
        return svc().deactivate(document_id)

    @app.post("/api/rebuild")
    def rebuild():
        return svc().rebuild()

    @app.post("/api/shutdown")
    def shutdown():
        if svc().operation:
            raise AppError("Wait until the current operation completes before stopping.", 409, "busy")
        callback = getattr(app.state, "shutdown_callback", None)
        if not callback:
            raise AppError("Use Ctrl+C to stop this development launch.", 409, "development_launch")
        callback()
        return {"status": "stopping"}

    @app.post("/api/upload")
    def upload(file: UploadFile = File(...), title: str = Form(...),
               department: str = Form("General"), version: str = Form(""),
               effective_date: str = Form(""), approved_for_demo: bool = Form(False),
               replace_document_id: str = Form("")):
        if not approved_for_demo:
            raise AppError("Confirm this file is suitable for the management demonstration.", 400, "not_reviewed")
        if not title.strip() or len(title) > 250:
            raise AppError("Enter a title of 1–250 characters.", 400, "invalid_title")
        ext = Path(file.filename or "").suffix.lower()
        if ext not in SUPPORTED:
            raise AppError("Supported formats: PDF, DOCX, TXT, Markdown.", 400, "invalid_format")
        metadata = {"title": title, "department": department[:120], "version": version[:120] or None,
            "effective_date": effective_date[:20] or None, "source_path": "Local file upload",
            "filename": Path((file.filename or "").replace("\\", "/")).name,
            "authority": "user_reviewed_demo_source", "authority_basis": "User explicitly cleared local upload for this demo.",
            "security_classification": "internal_management", "allowed_group": ["Management", "IT"],
            "demo_eligible": True, "status": "active"}
        if replace_document_id:
            svc().revision(replace_document_id)
            metadata["document_id"] = replace_document_id
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=svc().root / "data/uploads", suffix=ext, delete=False) as f:
                temporary = Path(f.name)
                size = 0
                while data := file.file.read(1024 * 1024):
                    size += len(data)
                    if size > 30 * 1024 * 1024:
                        raise AppError("Maximum upload is 30 MiB.", 413, "too_large")
                    f.write(data)
            return svc().index(temporary, metadata, force=bool(replace_document_id))
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
            file.file.close()

    @app.get("/api/sources/{chunk_id}")
    def source(chunk_id: str):
        return svc().source(chunk_id)

    @app.get("/api/documents/{document_id}/original")
    def original(document_id: str):
        r = svc().revision(document_id)
        if not r["active"]:
            raise AppError("This source is inactive.", 404, "inactive_source")
        meta = json.loads(r["metadata"])
        path = svc().root / r["vault_path"]
        return FileResponse(path, filename=meta["filename"], content_disposition_type="attachment")

    @app.get("/source/{chunk_id}", response_class=HTMLResponse)
    def preview(chunk_id: str):
        s = svc().source(chunk_id)
        esc = lambda v: html.escape(str(v or ""))
        page = f"Physical PDF page {s['page_number']}" if s["page_number"] else "No reliable physical page number"
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{esc(s['title'])}</title>
        <link rel="stylesheet" href="/static/styles.css"></head><body><main class="source-page">
        <a href="/">← Knowledge Assistant</a><p class="eyebrow">ORIGINAL EXTRACTED EVIDENCE</p>
        <h1>{esc(s['title'])}</h1><p>{esc(page)} · {esc(s['section'])}</p>
        <p>Version: {esc(s.get('version'))} · As of: {esc(s.get('source_as_of') or s.get('effective_date'))}</p>
        <p>{esc(s.get('review_notes'))}</p><pre class="excerpt">{esc(s['text'])}</pre>
        <a class="button" href="{esc(s['original_url'])}">Download original source</a>
        <p class="muted">Chunk {esc(s['id'])} · SHA-256 {esc(s['file_hash'])}</p>
        </main></body></html>"""

    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return app

app = create_app()
