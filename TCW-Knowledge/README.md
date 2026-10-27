# TCW office Knowledge Assistant

A local Python/FastAPI application for document questions with exact source excerpts, PDF page citations, DOCX section citations, document versions and retrieval diagnostics. The frontend is plain HTML/CSS/JavaScript. Ollama supplies embeddings and answer generation; SQLite and local-mode Qdrant persist the index.

This is the September 28, 2026 source baseline with small public-checkout adaptations documented in [the import record](../docs/REPOSITORY_IMPORT.md). The GIS patch is separate and has not been applied here.

## New development installation on Windows

1. Use a local NTFS folder. Keep this checkout separate from an existing working installation until its data/configuration and code have been compared.
2. Install Python 3.11–3.13 and Ollama if missing. Run `SETUP-TCW.cmd` from this folder. Setup creates `.venv`, installs the pinned requirements, preserves an existing `config/settings.json`, and downloads only missing configured models.
3. Run `START-TCW.cmd`; browse to `http://127.0.0.1:8765` on the host.
4. Upload approved documents in **Knowledge base**, or restore the approved private corpus manifest and its referenced source files locally. Nothing in the repository supplies district policy evidence.
5. Check **System & performance** for model/index availability, then ask a document question and inspect its excerpts.
6. Stop with `STOP-TCW.cmd`. See the known stale-token issue in the [handoff](../docs/CODEX_HANDOFF.md) if shutdown records are missing.

Default generation model: `qwen3.5:4b`. Default embedding model: `nomic-embed-text:v1.5`. The endpoint is `http://127.0.0.1:11434`. These are historical defaults, not a statement about the current host configuration. Changing the answer model does not rebuild the index; changing embedding identity requires a controlled rebuild.

Setup creates an empty, ignored `data/corpus_manifest.json` only when no manifest exists. An empty manifest is not an indexed corpus. The older UI still refers to the original curated corpus/holdout; those private files are deliberately absent from Git.

## Development and validation

Run `python -m pytest -q` from this folder after installing `requirements.txt`. Structural fixtures test storage and error boundaries; they do not test model accuracy. Two tests require private district sources and skip when absent.

`VALIDATE-TCW.cmd` requires the approved private `tests/validation_questions.json` and its documents. It also runs the designated holdout lifecycle exercise, which deactivates/imports/reindexes that test document. Inspect the dataset and run against the intended host/test corpus. For question-only validation, use `scripts\TCW.ps1 -Action Validate` without `-ExerciseLifecycle`.

Generated evidence remains local under `evidence/`. Review answer correctness, exceptions, scope and source authority manually. Mechanical citation checks alone do not establish factual correctness.

Useful operations are exposed through `scripts/TCW.ps1`: `Status`, `Index`, `Reindex`, `Rebuild`, `Validate`, `Backup`, `Audit`, `Tests` and `Logs`. Backups require a stopped app; do not copy a live Qdrant database or start multiple workers against one index.

## Deployment boundary

The web app is restricted to loopback and one worker. Its browser session token is not a staff login system. LAN access, per-user retrieval permissions and shared-office administration are unfinished. Keep Ollama and the BexDog private queue local to the host.
