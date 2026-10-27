# Repository import and validation — October 27, 2026

The starting repository contained only `README.md` at commit `dffe784f25a463481eb87fd1e67b3f3b48c2b922`. This import establishes a reviewable source baseline; it does not change or deploy to the Windows host.

## Source provenance

| Saved package | SHA-256 |
|---|---|
| `TCW_Knowledge_Assistant.zip` | `ed2f664ec524362e08d63837bcd5db0f8c7539e806a7caab3cb736d3da96f1dd` |
| `TCW_BexDog_ReadOnly_Addon.zip` | `c0d2ca039979c72adfaedbe22de75b1a85731c5c297f0d1a03b8b5ace743715c` |

Both saved packages were prepared September 28, 2026. The source selection includes 48 code/configuration/test files. Of these, 45 retain their exact archived bytes. [source-import.json](source-import.json) records every imported path and its source/repository hash. New README, handoff and repository-control files are authored for this import.

District source documents, private manifests and provider inventories, validation questions/answers, extracted evidence, screenshots, local settings, tokens, runtime data and binary ZIP packages are excluded. The complete BexDog source is also not included; the integration is a patch against a separately maintained project.

## Three public-checkout adaptations

- `TCW-Knowledge/scripts/Setup.ps1` creates an empty local corpus manifest only if absent and tells users to supply approved documents. Existing private manifests are preserved. UTF-8 is written without a BOM for the original JSON reader.
- `TCW-Knowledge/tests/test_components.py` explicitly skips the two private-corpus checks when their required sources are absent, instead of claiming extraction success with no documents or failing a public checkout for missing district files.
- `TCW-Knowledge/scripts/validate_live.py` exits with a clear blocked message and code 2 if the private acceptance dataset is missing. It does not generate substitute questions or answers.

All legacy patch payloads and the five original app files pinned by the installer remain byte-identical to the archives. `.gitattributes` preserves the archived line endings across Windows checkouts: LF source and CRLF in the four legacy command launchers. The importer did not apply the GIS patch or fix the historical shutdown/path-validation bugs; those are documented continuation tasks.

## Executed for this import

| Check | Result | Limit |
|---|---|---|
| Pinned Python dependency installation | Passed in an isolated Python 3.12 Linux environment | Top-level versions are pinned; transitive dependencies are not fully locked. |
| Base app component suite | 15 passed, 2 skipped | Private-corpus checks skipped; synthetic fixtures do not measure model accuracy. |
| Base app plus GIS patch in a disposable copy | 36 passed, 2 skipped | Includes 21 GIS control/transport checks; this is not an installer run or live GIS test. |
| Legacy compatibility hashes | All 21 available original-app/payload/SDK-patch hashes matched | Full BexDog dependency hashes cannot be verified without the current source project. |
| Python parsing | All 20 imported Python files parsed | Does not compile C# or execute PowerShell. |
| JavaScript parsing | Both base and patched frontend scripts passed `node --check` | No new browser UI acceptance run. |
| Missing private live-validation dataset | Clear blocked message, exit 2 | No local-model validation was performed. |

Both Python test runs emitted one upstream Starlette TestClient/httpx deprecation warning. Tests completed successfully; no dependency versions were changed to silence it.

The repository export is explicitly limited to tracked code/docs/configuration examples. Runtime files generated during tests remain ignored. Review the staged file list and source provenance before publishing any later additions; a `.gitignore` cannot sanitize a file already committed or pasted into an issue.

## Historical claims versus current checks

The September documents recorded 17 original component checks; the add-on recorded those 17 plus 21 GIS checks, six disconnected browser checks and 13 installer/source checks. These are historical records, not additional October executions. The two private-source tests account for the difference between historical full component totals and this public import's passed counts.

Not executed here: PowerShell/CMD setup and stop, Windows ACL isolation, C# harness, actual ArcGIS SDK build, real maps/geodatabases/DEM queries, live native-read cancellation, real Ollama generation, semantic policy regression, staff identity, second-workstation access or LAN deployment. No such acceptance is implied by successful component tests.
