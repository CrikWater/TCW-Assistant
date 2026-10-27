using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;

namespace TCW_EngineeringAssistant
{
    public partial class Dockpane1View
    {
        private const string TcwBridgeProtocol = "tcw-gis-readonly-v1";
        private readonly string _tcwBridgeSession = Guid.NewGuid().ToString("N");
        private string _tcwBridgeRoot;
        private FileStream _tcwBridgeLease;
        private DispatcherTimer _tcwBridgeTimer;
        private bool _tcwBridgeProcessing;
        private string _tcwBridgeJob;
        private long _tcwBridgeLastHeartbeat;
        private int _tcwBridgeTick;
        private static long TcwNow() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        // Called once after InitializeComponent, through the hash-checked installer.
        private void InitializeTcwReadOnlyBridge()
        {
            try
            {
                _tcwBridgeRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "TCW", "BexDogReadOnlyBridge");
                Directory.CreateDirectory(_tcwBridgeRoot);
                using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                {
                    var security = new DirectorySecurity();
                    security.SetAccessRuleProtection(true, false);
                    security.SetOwner(identity.User);
                    foreach (SecurityIdentifier sid in new[] { identity.User, new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null) })
                        security.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                            PropagationFlags.None, AccessControlType.Allow));
                    new DirectoryInfo(_tcwBridgeRoot).SetAccessControl(security);
                }
                // A second ArcGIS Pro process cannot impersonate the active provider.
                _tcwBridgeLease = new FileStream(Path.Combine(_tcwBridgeRoot, "provider.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
                _tcwBridgeTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(250) };
                _tcwBridgeTimer.Tick += TcwReadOnlyBridgeTick;
                Dispatcher.ShutdownStarted += (_, _) =>
                {
                    _tcwBridgeTimer.Stop();
                    if (_tcwBridgeProcessing) _requestCts?.Cancel();
                    _tcwBridgeLease.Dispose();
                };
                _tcwBridgeTimer.Start();
            }
            catch (Exception ex)
            {
                _tcwBridgeLease?.Dispose();
                StatusText.Text = "Read-only web bridge unavailable: " + ex.GetType().Name;
            }
        }

        private async void TcwReadOnlyBridgeTick(object sender, EventArgs e)
        {
            try
            {
                if (_tcwBridgeJob != null && File.Exists(Path.Combine(_tcwBridgeRoot, _tcwBridgeJob + ".cancel")))
                    _requestCts?.Cancel();
                if (TcwNow() - _tcwBridgeLastHeartbeat >= 1000)
                {
                    TcwWrite("provider.json", new
                    {
                        protocol = TcwBridgeProtocol, session_id = _tcwBridgeSession,
                        heartbeat_ms = TcwNow(), read_only = true, bexdog_version = BexDogMemoryVersion,
                        busy = _requestCts != null, job_id = _tcwBridgeJob,
                        cancellation_pending = _tcwBridgeProcessing && _requestCts?.IsCancellationRequested == true
                    });
                    _tcwBridgeLastHeartbeat = TcwNow();
                }
                if (_tcwBridgeProcessing) return;
                // Expired transport artifacts are never replayed. No GIS files are touched.
                if (++_tcwBridgeTick % 240 == 0)
                    foreach (string f in Directory.EnumerateFiles(_tcwBridgeRoot).Take(256))
                        if ((f.EndsWith(".request.json") || f.EndsWith(".response.json") || f.EndsWith(".cancel")) &&
                            File.GetLastWriteTimeUtc(f) < DateTime.UtcNow.AddMinutes(-10)) File.Delete(f);
                string requestPath = Directory.EnumerateFiles(_tcwBridgeRoot, "*.request.json").Take(32).OrderBy(File.GetLastWriteTimeUtc).FirstOrDefault();
                if (requestPath == null) return;
                _tcwBridgeProcessing = true;
                try { await TcwProcessRequest(requestPath); }
                finally { _tcwBridgeProcessing = false; }
            }
            catch (Exception ex)
            {
                StatusText.Text = "Read-only web bridge transport error: " + ex.GetType().Name;
            }
        }

        private async Task TcwProcessRequest(string path)
        {
            string id = Path.GetFileName(path).Replace(".request.json", "");
            if (!Guid.TryParseExact(id, "N", out _) || new FileInfo(path).Length > 16384) { File.Delete(path); return; }
            JsonElement req;
            try { using var doc = JsonDocument.Parse(await File.ReadAllTextAsync(path)); req = doc.RootElement.Clone(); }
            catch (JsonException) { File.Delete(path); return; }
            string job = null;
            long deadline = 0;
            object reply;
            CancellationTokenSource owned = null;
            string oldStatus = StatusText.Text;
            try
            {
                var keys = new HashSet<string>(StringComparer.Ordinal);
                string[] allowed = { "protocol", "id", "job_id", "session_id", "created_ms", "deadline_ms", "operation", "payload", "expected_map_uri" };
                foreach (var p in req.EnumerateObject())
                    if (!keys.Add(p.Name) || !allowed.Contains(p.Name)) throw new InvalidOperationException("Invalid request envelope.");
                if (req.GetProperty("protocol").GetString() != TcwBridgeProtocol || req.GetProperty("session_id").GetString() != _tcwBridgeSession || req.GetProperty("id").GetString() != id)
                    throw new InvalidOperationException("Request session mismatch.");
                job = req.GetProperty("job_id").GetString();
                if (!Guid.TryParseExact(job, "N", out _)) throw new InvalidOperationException("Invalid request owner.");
                long created = req.GetProperty("created_ms").GetInt64();
                deadline = req.GetProperty("deadline_ms").GetInt64();
                if (deadline <= TcwNow() || created > TcwNow() + 5000 || deadline - created > 120000 || deadline <= created)
                    throw new InvalidOperationException("Request expired or exceeds the time limit.");
                if (_requestCts != null) throw new InvalidOperationException("BexDog is busy with another request.");
                if (File.Exists(Path.Combine(_tcwBridgeRoot, job + ".cancel"))) throw new OperationCanceledException();
                owned = new CancellationTokenSource(TimeSpan.FromMilliseconds(deadline - TcwNow()));
                _requestCts = owned;
                _tcwBridgeJob = job;
                SetBusy(true);
                StatusText.Text = "Read-only web query in progress. Cancel is available.";
                string operation = req.GetProperty("operation").GetString();
                JsonElement payload = req.GetProperty("payload");
                string mapJson = await ArcGisToolService.ExecuteAsync("get_active_map", EmptyJsonElement());
                using var mapDoc = JsonDocument.Parse(mapJson);
                JsonElement map = mapDoc.RootElement.Clone();
                string mapUri = map.TryGetProperty("map_uri", out var uri) ? uri.GetString() : null;
                if (req.TryGetProperty("expected_map_uri", out var expected) && expected.ValueKind == JsonValueKind.String && expected.GetString() != mapUri)
                    throw new InvalidOperationException("The active map changed. Start a new question.");
                object data;
                if (operation == "catalog")
                {
                    if (payload.ValueKind != JsonValueKind.Object || payload.EnumerateObject().Any()) throw new InvalidOperationException("Catalog takes no arguments.");
                    data = new
                    {
                        map, glossary = TcwWaterUtilityKnowledgeBase.BuildCompactPromptContext(),
                        tools = TcwReadOnlyTools.Tools.Select(p => new { name = p.Key, description = p.Value.Description, parameters = p.Value.Parameters }).ToArray()
                    };
                }
                else if (operation == "tool")
                {
                    if (payload.ValueKind != JsonValueKind.Object || payload.EnumerateObject().Count() != 2 || !payload.TryGetProperty("tool", out var name) || !payload.TryGetProperty("arguments", out var args))
                        throw new InvalidOperationException("Only a named read-only tool and its bounded arguments are accepted.");
                    string raw = await TcwReadOnlyTools.ExecuteAsync(name.GetString(), args, owned.Token);
                    if (Encoding.UTF8.GetByteCount(raw) > 1800000)
                        throw new InvalidOperationException("GIS result exceeds the bridge size limit. Narrow the query.");
                    using var result = JsonDocument.Parse(raw);
                    data = result.RootElement.Clone();
                }
                else throw new InvalidOperationException("Unknown read-only operation.");
                owned.Token.ThrowIfCancellationRequested();
                if (File.Exists(Path.Combine(_tcwBridgeRoot, job + ".cancel"))) throw new OperationCanceledException();
                string afterJson = await ArcGisToolService.ExecuteAsync("get_active_map", EmptyJsonElement());
                using var after = JsonDocument.Parse(afterJson);
                string afterUri = after.RootElement.TryGetProperty("map_uri", out var au) ? au.GetString() : null;
                if (mapUri != afterUri) throw new InvalidOperationException("The active map changed during the read. Result discarded.");
                owned.Token.ThrowIfCancellationRequested();
                if (File.Exists(Path.Combine(_tcwBridgeRoot, job + ".cancel"))) throw new OperationCanceledException();
                reply = new { status = "ok", data, map_uri = mapUri };
            }
            catch (OperationCanceledException) { reply = new { status = "cancelled", error = "The host cancelled this request or its time limit expired." }; }
            catch (Exception ex) { reply = new { status = "error", error = ex is InvalidOperationException ? ex.Message : "SDK read failed: " + ex.GetType().Name }; }
            finally
            {
                // Never free the BexDog UI while an uninterruptible ArcGIS read still runs.
                // We reach here only after its await completes.
                if (owned != null)
                {
                    if (ReferenceEquals(_requestCts, owned)) _requestCts = null;
                    owned.Dispose();
                    _tcwBridgeJob = null;
                    SetBusy(false);
                    StatusText.Text = oldStatus;
                    _tcwBridgeLastHeartbeat = 0;
                }
            }
            if (deadline > TcwNow() && File.Exists(path))
                TcwWrite(id + ".response.json", new
                {
                    protocol = TcwBridgeProtocol, id, job_id = job, session_id = _tcwBridgeSession,
                    completed_ms = TcwNow(), read_only = true, reply
                });
            File.Delete(path);
        }

        private void TcwWrite(string filename, object value)
        {
            string json = JsonSerializer.Serialize(value);
            if (Encoding.UTF8.GetByteCount(json) > 2 * 1024 * 1024)
                throw new InvalidOperationException("GIS result exceeds the transport limit. Narrow the query.");
            string target = Path.Combine(_tcwBridgeRoot, filename);
            string temp = target + ".tmp";
            File.WriteAllText(temp, json, new UTF8Encoding(false));
            File.Move(temp, target, true);
        }
    }
}
