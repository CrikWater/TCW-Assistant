// Structural permission-boundary checks only. NO ArcGIS data or actual SDK runtime.
using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using TCW_EngineeringAssistant;

int passed = 0;
foreach (string name in new[] { "delete_feature", "update_feature", "validate_topology", "run_python", "remember_operator_fact", "export_csv", "hydraulics", "GET_ACTIVE_MAP" })
    Reject(name, "{}");
Reject("get_active_map", "{\"command\":\"anything\"}");
Reject("query_layer_data", "{\"layer_name\":\"TEST FIXTURE\",\"action\":\"query\",\"where_clause\":\"DELETE FROM fixture\"}");
Reject("query_layer_data", "{\"layer_name\":\"TEST FIXTURE\",\"action\":\"delete\"}");
Reject("get_selection", "{\"layer_name\":\"TEST FIXTURE\",\"max_features\":101}");
Reject("summarize_layer", "{\"layer_name\":\"TEST FIXTURE\",\"filters\":[{\"field\":\"ID\",\"operator\":\"execute\",\"value\":\"anything\"}]}");
Reject("describe_layer", "{}");
Reject("describe_layer", "{\"layer_name\":\"\"}");
Reject("describe_layer", "{\"layer_name\":\"a\",\"layer_name\":\"b\"}");
using (var valid = JsonDocument.Parse("{\"layer_name\":\"TEST FIXTURE\",\"filters\":[{\"field\":\"ID\",\"operator\":\"equals\",\"value\":\"1\"}]}"))
    TcwReadOnlyTools.Validate("summarize_layer", valid.RootElement);
passed++;
if (BoundaryStub.Calls != 0) throw new Exception("A rejected call reached a service dispatcher.");
Console.WriteLine($"{passed} read-only boundary checks passed using inert service stubs. This is not a live ArcGIS test.");
void Reject(string name, string args)
{
    using var json = JsonDocument.Parse(args);
    bool rejected = false;
    try { TcwReadOnlyTools.ExecuteAsync(name, json.RootElement, CancellationToken.None).GetAwaiter().GetResult(); }
    catch (InvalidOperationException) { rejected = true; }
    if (!rejected) throw new Exception("Unexpectedly allowed: " + name);
    passed++;
}
namespace TCW_EngineeringAssistant
{
    internal static class BoundaryStub { internal static int Calls; internal static Task<string> Run() { Calls++; return Task.FromResult("{}"); } }
    internal static class ArcGisToolService { internal static Task<string> ExecuteAsync(string name, JsonElement args) => BoundaryStub.Run(); }
    internal static class TcwGdbWorkspaceService { internal static Task<string> ExecuteAsync(string name, JsonElement args) => BoundaryStub.Run(); }
    internal static class ElevationToolService { internal static Task<string> ExecuteAsync(string name, JsonElement args, CancellationToken token) => BoundaryStub.Run(); }
}
