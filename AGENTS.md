# Work in this repository

Read `docs/CODEX_HANDOFF.md` before implementation. This repository contains the office document assistant and a separate historical GIS integration patch. It is not the full BexDog source project.

- Preserve the host's existing corpus, index, configuration, models and production GIS data. Discover the actual installation and source paths before applying changes.
- GIS access exposed to staff must be read only. Accept free-form questions; enforce tool names, argument schemas and permissions at the execution boundary. Never route office requests through a general agent, script, shell or write-capable dispatcher.
- Preserve host cancel, pause and resume controls. Report cancellation pending honestly while a native read is still running. Do not force-kill ArcGIS Pro or unrelated Python/Ollama processes.
- Keep this public repository free of district documents, extracted evidence, GIS datasets, runtime state, credentials, local configuration and internal network details. Use synthetic fixtures in public tests.
- The historical patch is pinned to specific September 2026 source hashes. Compare it with current BexDog code; do not bypass compatibility checks or rename a project just to satisfy the old installer.
- The shipped web app is loopback-only. Changing the bind address is not a complete LAN deployment. Add identity, authorization, requester attribution and owner controls before staff access.
- Run relevant existing component tests. Distinguish synthetic tests from real-model, Windows and ArcGIS acceptance. Preserve exact citations, exceptions and uncertainty; quote validation alone does not prove a claim.
- Keep existing BexDog model routing separate from the office assistant's local inference configuration unless the user requests a coordinated change.

From `TCW-Knowledge`, run `python -m pytest -q` with the pinned requirements installed. Private-corpus checks skip explicitly when their input is absent. See `docs/REPOSITORY_IMPORT.md` for source provenance and current validation limits.
