# TCW Assistant

Office document questions with cited evidence, plus a separate read-only BexDog integration reference.

**Start with [the Codex handoff](docs/CODEX_HANDOFF.md).** It records the working document assistant, the unfinished GIS installation, host veto requirements and the next implementation steps.

| Folder | Purpose |
|---|---|
| [TCW-Knowledge](TCW-Knowledge/) | Python/FastAPI office assistant, browser UI, Ollama integration, local document storage and Windows launchers. |
| [integrations/TCW_BexDog_ReadOnly_Addon](integrations/TCW_BexDog_ReadOnly_Addon/) | Historical September 28 source patch for a specific BexDog version. Not applied to the app above; not a compiled add-in. |
| [docs](docs/) | Codex handoff, import provenance and validation status. |

The source is based on the saved September 28, 2026 packages. It is not a snapshot of the host computer's current installation. The document assistant was demonstrated by the user's actual answers. The conversation does not establish a successful GIS patch installation, ArcGIS build or shared-office deployment.

This public repository contains code and documentation. District documents, corpus manifests, validation answers, indexes, local settings, credentials and generated evidence stay on the host. A new checkout starts without documents; it cannot answer district policy questions until approved sources are supplied locally.

For a new development installation, follow [TCW-Knowledge/README.md](TCW-Knowledge/README.md). Compare source and back up the existing installation before updating a working host. Keep the current loopback listener until the LAN access requirements in the handoff are implemented and tested.
