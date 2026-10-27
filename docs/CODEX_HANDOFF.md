# TCW Assistant — Codex handoff

Prepared October 27, 2026 from the visible project conversation, the two saved September 28 release packages and this repository's initial README. This handoff does not claim access to the current Windows installation or a current BexDog checkout.

## Mission and repository

Use [CrikWater/TCW-Assistant](https://github.com/CrikWater/TCW-Assistant) as the source home for the office TCW AI assistant. Preserve the working document-question workflow and the host's indexed data. Complete a strictly read-only GIS connection to BexDog, preserve host veto controls, then prepare authenticated office-network access.

`TCW-Knowledge/` is the original document application. `integrations/TCW_BexDog_ReadOnly_Addon/` is an unapplied historical patch. BexDog is a separate C#/ArcGIS Pro SDK project. The hosted Technology Command Center supplied some historical source records and a map link; the SDK bridge did not modify that hosted site. A link or embedded map alone does not expose the SDK's live querying capability.

This repository was public and contained only a short README when inspected. The import intentionally omits district documents, source inventories/IDs, validation answer datasets, internal network details, GIS data, settings, runtime databases, credentials and generated evidence. Restore private inputs on the authorized workstation, not in public Git history.

## Requirements from the user

- Staff may ask any natural-language question; there must not be a fixed menu of permitted question wording.
- GIS execution must be **READ ONLY**. Enforce permissions independently of the model's prompt. Prohibit feature/schema/topology edits, selection changes, arbitrary scripts/SQL, exports and generic write-capable dispatch through this interface.
- The host owner can veto an active BexDog request, pause further calls and resume explicitly. Display the requester and job when shared identity exists.
- Do not claim immediate termination of a native ArcGIS read that cannot be interrupted. Suppress its answer, prevent subsequent calls and keep the SDK busy until the read returns.
- Preserve real documents, exact source evidence and uncertainty. An unsupported question must not produce a fabricated answer.
- Preserve current corpus/index/settings and the user's existing BexDog work. Keep BexDog's current model routing separate from the office app unless a coordinated change is requested.

## What is established, and what is pending

| Area | Evidence/status |
|---|---|
| Document indexing and answering | The user indexed sources and posted real policy answers with excerpts and retrieval timings. Current document count and current deployed code are not independently verified. |
| Repeat query performance | User reported retrieval dropping from 13.31 s to 0.89 s and total time from 46.80 s to 18.06 s. Generation was about 49.4 tokens/s. This does not identify the exact cause of the difference. |
| Citation correctness | Exact excerpts and citation checks were displayed. They did not prevent omitted exceptions or broader paraphrasing. |
| GIS source patch | Packaged, with historical Python/control and disconnected browser checks. Not demonstrated live in this conversation. |
| Installation | Last observed attempt stopped because one or both application/project roots did not satisfy installer checks. No successful apply/build was shown. |
| Host veto | Implemented in the historical source patch; live Windows/ArcGIS behavior remains unverified. |
| Staff/LAN access | Not implemented or verified by these releases. Web server remains loopback-only. |
| Current source | September packages are a reference baseline. Inspect current local files and repository history before deciding what to port. |

## Application architecture and code map

| Path under `TCW-Knowledge/` | Responsibility |
|---|---|
| `backend/app.py` | FastAPI routes, session-token/same-origin checks, source previews, uploads and document administration. |
| `backend/service.py` | Serialized indexing/query operations, document revisions, deduplication, SQLite metadata, Qdrant vectors and metrics. |
| `backend/inference.py` | Loopback Ollama calls, local model checks, embeddings and structured generation. |
| `backend/config.py` | Example configuration plus local overrides; loopback endpoint validation. |
| `backend/cli.py` | Serve/status/index/reindex/rebuild/audit/backup commands; one worker bound to `127.0.0.1`. |
| `ingestion/extract.py` | PDF/DOCX/text/Markdown extraction and chunking; credential-pattern and unresolved tracked-change rejection. |
| `retrieval/grounding.py` | Evidence prompt, answer schema, exact quotes/citations, numerical checks and partial/unknown/conflict statuses. |
| `frontend/` | Ask documents, Knowledge base, System/performance; the separate patch adds Ask the map. |
| `scripts/` and root `.cmd` files | Windows setup/start/stop/preflight/operations and live acceptance runner. |
| `tests/test_components.py` | Structural storage, lifecycle, citation and boundary tests, plus two private-source checks. |

Historical defaults are Ollama `http://127.0.0.1:11434`, web port `8765`, generator `qwen3.5:4b` and embeddings `nomic-embed-text:v1.5`. The user already had multiple Qwen, Phi, Granite and Ministral models installed. Read the actual `config/settings.json` and `ollama list`; do not reinstall models unnecessarily or assume these defaults are still selected.

Changing the generator preserves the vector index. Changing embedding identity requires a deliberate rebuild. A single busy lock serializes app work; SQLite and local-mode Qdrant must not be shared by multiple server workers. The browser's per-launch token protects local POST requests; it is not an authenticated staff identity.

Private runtime state lives under `data/`, `logs/`, `evidence/` and `config/settings.json`. The original package had seven curated startup documents and a separate ingestion holdout. Its extraction audit prepared 359 startup chunks plus 21 holdout chunks; these are not a measurement of the user's current searchable index. Private source provenance and authority assessments belong in the local corpus manifest.

## Where installation stopped

Historical user-reported paths:

| Purpose | Path reported in the conversation |
|---|---|
| Existing office app | `C:\TCW-Knowledge` |
| Extracted integration package | `C:\TCW_BexDog_ReadOnly_Addon` |
| BexDog source folder supplied to installer | `C:\GIS_AI\src\TCW.EngineeringAssistant` |

These are discovery hints, not proof of current paths. The two TCW folders were placed separately off `C:\`. The actual BexDog `.csproj` location was not resolved in the conversation.

1. Installation repeatedly stopped because `logs/session-token` existed.
2. `STOP-TCW.cmd` reported no process record. At that time, the user's port-8765 listener check and `backend.cli ... serve` process check returned no rows.
3. After those checks, the user removed that one stale token file. This was a historical action, not standing permission to delete a token during a future session.
4. The next preflight advanced to:

   `INSTALL STOPPED: Point --tcw-root at TCW-Knowledge and --bexdog-root at the directory containing the .csproj.`

The actual installer checks **both** `<tcw-root>/backend/app.py` and `<bexdog-root>/TCW_EngineeringAssistant.csproj`. Its message does not identify which failed. A nested extraction directory, a different project folder or a changed project name could cause this. Do not assume the dotted folder name means the project is wrong, and do not rename a project to satisfy the check.

`Stop.ps1` has two early returns that can leave a stale session token: absent PID record and recorded process no longer present. The legacy installer also incorrectly names `Stop.cmd` instead of `STOP-TCW.cmd` in its error message. Both issues remain in the imported baseline and are concrete follow-up fixes.

## Start with read-only discovery

On the actual Windows host, first read applicable repository instructions and inspect the current working tree. For the paths reported above, these checks disclose paths/status without printing tokens or configuration contents:

```powershell
$tcwRoot = 'C:\TCW-Knowledge'
$bexdogHint = 'C:\GIS_AI\src\TCW.EngineeringAssistant'

[pscustomobject]@{
    TcwAppFound = Test-Path -LiteralPath (Join-Path $tcwRoot 'backend\app.py')
    PythonFound = Test-Path -LiteralPath (Join-Path $tcwRoot '.venv\Scripts\python.exe')
    ExpectedProjectFound = Test-Path -LiteralPath (Join-Path $bexdogHint 'TCW_EngineeringAssistant.csproj')
    SessionMarkerPresent = Test-Path -LiteralPath (Join-Path $tcwRoot 'logs\session-token')
}
Get-ChildItem -LiteralPath $bexdogHint -Filter '*.csproj' -File -Recurse -ErrorAction Stop |
    Select-Object FullName
Get-NetTCPConnection -State Listen -ErrorAction Stop |
    Where-Object LocalPort -eq 8765 |
    Select-Object LocalAddress, LocalPort, OwningProcess
Get-CimInstance Win32_Process -ErrorAction Stop |
    Where-Object { $_.CommandLine -match 'backend\.cli.*serve' -or $_.Name -eq 'ArcGISPro.exe' } |
    Select-Object ProcessId, Name, ExecutablePath
```

If a path is absent, locate the active project in the user's known source folders/drives. If the app's configured port changed, repeat the listener check for that port. A query failure or an incomplete command-line filter is not proof that the app is stopped. Do not run `--apply`, delete session markers, stop indexing, or kill processes as part of discovery.

Read the current `.csproj`, target framework, ArcGIS SDK references, dockpane constructor and the three read-service implementations. Compare hashes/diffs against `compatibility.json`. The original patch targeted `1.5.3-compound-orchestration`, expected `TCW_EngineeringAssistant.csproj`, and referenced a `net10.0-windows` project. That historical target is not an instruction to retarget today's project or replace installed SDK assemblies.

## GIS bridge design available for reuse

The add-on contains two C# source files and a constructor hook, plus office backend/frontend changes. It is not a standalone GIS server.

`TcwReadOnlyTools.cs` independently validates an explicit 30-tool registry and arguments, then calls `ArcGisToolService`, `TcwGdbWorkspaceService` or `ElevationToolService` directly. The registered operations cover map/layer/schema discovery, current-selection reads, bounded attributes and aggregates, spatial measurements, approved-workspace reads, Utility Network evidence and qualified DEM reads. There is no general agent dispatcher, arbitrary `where_clause`, shell, script, feature edit, selection change or export route.

`TcwReadOnlyBridge.cs` exchanges expiring JSON files with the office backend in the same Windows account's `%LOCALAPPDATA%\TCW\BexDogReadOnlyBridge` directory. It uses correlated request/job/provider-session IDs, heartbeat freshness, a provider lock, bounded payloads and active-map checks. This is not a transactional snapshot of concurrently edited data.

The office patch adds `backend/gis_bridge.py`, `backend/gis_service.py`, `backend/owner_credentials.py`, `scripts/gis_owner.py`, GIS routes and the Ask the map UI. The model proposes a tool from the supplied catalog; Python checks the proposal and C# enforces its own boundary. Final answers use tool evidence; raw SDK output, parameters and timing remain inspectable. Truncated model context and incomplete tool scans must remain visible.

Historical limits: one active question, eight model-selected tool steps, five minutes per question and two minutes per SDK transport request. Expired or mismatched responses must not be reused. Confirm these limits against current code before deployment.

Read-only here means **no writes to source GIS data through this interface**. Queue/log/token/pause files and an existing non-GIS metadata cache are still written. The interface does not remove broader write permissions from the host's ArcGIS desktop session. For shared service, evaluate separately permissioned read-only sources/credentials without breaking the host's editing workflow.

## Host veto and staff access

The patch supplies `BexDog_Status.cmd`, `Cancel_BexDog.cmd`, `Pause_BexDog.cmd` and `Resume_BexDog.cmd`. Cancel pauses new questions; pause state survives app restart. Owner credentials live separately from browser tokens under a Windows ACL-protected `%LOCALAPPDATA%\TCW\KnowledgeOwner` folder. Ordinary browser credentials must never grant owner control.

The cancel script has a direct SDK marker fallback if the web control endpoint is unresponsive. Cancellation closes/suppresses the answer pipeline and prevents subsequent tools. A running native SDK read can remain busy until it returns; a frozen ArcGIS UI may not process its timer at all. Do not release busy state early or promise a force-kill recovery mechanism that is not implemented.

Individual staff identity and per-person access revocation are not implemented. The historical veto applies to the active job and can pause everyone; it cannot yet reliably identify and remove a particular signed-in remote person.

For office access, staff browsers should connect to an authenticated host endpoint. Ollama, ArcGIS and the private queue stay on the host. `127.0.0.1` on a staff PC points to that staff PC, not the host. Discover the host's current LAN address/DNS; the historical DHCP address is not a deployment guarantee. Changing the web bind address alone leaves authentication and authorization unfinished.

LAN work must cover sign-in, viewer/admin separation, source/document permissions, requester attribution, per-user revocation, owner priority/cancellation, timeouts/concurrency, appropriate TLS/firewall scope, and working source links from a second workstation. Ordinary viewers must not inherit upload, deactivation, model changes, rebuild or shutdown privileges. A public hosted command-center page cannot be assumed to reach a private workstation endpoint or supply identity for it.

## Document answer quality to preserve and improve

The user-posted answer demonstrated useful retrieval, but omitted a material policy exception, broadened the people covered by a fee statement, and lacked the full context of a referenced exception section. The original question was not included, so the answer's completeness cannot be fully reconstructed from the transcript alone.

The historical patch strengthens `retrieval/grounding.py` to preserve qualifiers and mark missing cross-reference context as partial. No live rerun establishes that this fixed the behavior. Obtain the original question, retrieve the relevant adjacent/referenced sections, and compare the complete cited statements on the host. A filename date is not proof of the governing approved version. Add public synthetic regression examples for these reasoning failures without publishing district policy text.

## Prioritized continuation

1. **Discover and preserve.** Locate current code and installations, inspect status, and compare with this baseline. Finish existing work before a controlled stop; create a consistent backup of private state before deployment changes.
2. **Fix installation diagnostics and shutdown bookkeeping.** Report each checked path separately. Clean a stale marker only after positively establishing that this app is inactive. Preserve checks that prevent patching a running app, PID reuse mistakes and accidental overwrite. Do not bypass source hashes.
3. **Port the read-only boundary into current BexDog.** Reuse the design, audit current direct service calls, keep existing model routing intact, and build against the actually installed ArcGIS SDK. Preserve existing user edits and constructor behavior.
4. **Verify GIS and veto locally.** Use a disposable GIS project/copy for adversarial checks. Establish live provenance, measurements and cancellation behavior before office access.
5. **Repair document scope/exception handling.** Retest the actual policy question privately and extend synthetic regressions. Preserve the current index unless a documented extraction/embedding change requires migration.
6. **Implement shared access.** Add identity/authorization and operator controls, then demonstrate use from a second office workstation. Record actual permissions, timing and limitations.

## Acceptance evidence required

- Existing indexed documents, revisions, source links and settings survive source updates and restart.
- Ordinary document answers retain exact excerpts, qualifiers and unsupported/partial/conflict handling.
- Current C# build succeeds against the installed ArcGIS Pro SDK; the inert boundary harness is recorded separately.
- Live counts/selections/spatial measurements match independent ArcGIS checks with units, definition-query scope, timestamps and scan limits visible.
- Attempts to edit/delete/move features, change selection, export, validate topology or execute scripts cannot invoke those actions through the interface. Verify actual source state on a disposable copy; timestamps alone are insufficient.
- Host cancel suppresses output and further calls, retains busy state during a native read, and keeps pause across refresh/restart until explicit resume.
- A second ordinary Windows account cannot read owner credentials or write private queue requests; browser tokens alone cannot use owner controls.
- After identity is implemented, a second staff workstation can ask permitted questions and follow citations; the host can identify/revoke the requester and cancel their job. Viewer accounts cannot administer the app.
- Offline, expired, cancelled, unsupported and incomplete results remain explicit. No synthetic answers appear as live GIS or district evidence.

See [REPOSITORY_IMPORT.md](REPOSITORY_IMPORT.md) for the October 27 checks and the distinction from historical test claims. The next Codex session should implement from verified current source, not assume this handoff proves deployment.
