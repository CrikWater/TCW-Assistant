# Historical TCW–BexDog read-only integration

**Version 0.1.0, September 28, 2026. Integration reference; not installed by this repository import.**

This source patch targets the originally attached BexDog `1.5.3-compound-orchestration` project. The full BexDog project and ArcGIS libraries are not included. Compare current source before reusing it. The last user-reported install attempt stopped at root/project-path validation; there is no confirmed live GIS deployment in the handoff conversation.

| Material | Role |
|---|---|
| `sdk/TcwReadOnlyTools.cs` | Independent 30-tool allowlist, argument validation and direct read-service dispatch. |
| `sdk/TcwReadOnlyBridge.cs` | Same-account file queue, provider/session identity, deadlines, busy state and cancellation markers. |
| `app_patch/` | Replacement/additional office app files, Ask the map UI, model planning, separate owner controls and tests. |
| `compatibility.json` | Hashes of the exact reviewed app/SDK inputs and patch payload. |
| `install.py` | Preview-first, hash-checked installer with backup receipt and protected rollback. |
| `tests/SdkBoundaryTests/` | Inert C# rejection harness; does not validate real GIS results or build the add-in. |

All imported executable patch files and `compatibility.json` retain their archived bytes. The README is new; archived operational records and evidence are not published.

The installer requires `<tcw-root>/backend/app.py` and `<bexdog-root>/TCW_EngineeringAssistant.csproj`. The expected project filename uses an underscore. A folder with a dotted name may still contain that file; inspect it rather than renaming anything. The constructor hook is `InitializeTcwReadOnlyBridge();` in `EngineeringAssistantDockpane.xaml.cs`.

The source patch belongs outside both target projects so backup `.cs` files cannot be compiled accidentally. The repository's sibling layout satisfies that layout requirement, but it does not establish SDK compatibility. Read [the handoff](../../docs/CODEX_HANDOFF.md) before applying. Do not disable hashes, automatically delete a session token or force-stop an unrelated process to make installation proceed.

The bridge accepts free-text questions, but executes only permitted reads. It never calls the general BexDog agent/workflow, shell or write dispatcher. Local application transport, pause and credential files are written; source GIS data must remain unchanged. The host's wider ArcGIS desktop account is not made read-only by this patch.

Owner commands supplied by the patch are `BexDog_Status.cmd`, `Cancel_BexDog.cmd`, `Pause_BexDog.cmd` and `Resume_BexDog.cmd`. Cancel also pauses new questions. Native SDK reads may remain busy until they return; the app must discard cancelled results and start no further tools. No forced ArcGIS termination is implemented.

The web listener remains loopback-only. Windows ACLs, the current SDK build, live queries, cancellation and eventual user identity/authorization need workstation acceptance. See the handoff's acceptance gates.
