using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace TCW_EngineeringAssistant
{
    // This is the execution boundary. Never dispatch through the general BexDog
    // agent, workflow, external-worker, memory, or shell dispatchers.
    internal static class TcwReadOnlyTools
    {
        internal sealed record Spec(string Service, string Description, Dictionary<string, string> Parameters);
        private static Spec S(string service, string description, string parameters = "") => new(
            service, description, parameters.Split(' ', StringSplitOptions.RemoveEmptyEntries)
                .Select(x => x.Split(':')).ToDictionary(x => x[0], x => x[1], StringComparer.Ordinal));
        internal static readonly IReadOnlyDictionary<string, Spec> Tools = new Dictionary<string, Spec>(StringComparer.Ordinal)
        {
            ["get_active_map"] = S("map", "Read active map identity, CRS and selection count."),
            ["list_layers"] = S("map", "List loaded layers; this does not add or change layers."),
            ["find_layers"] = S("map", "Resolve actual layers from a name or utility concept.", "search_term:string!"),
            ["describe_layer"] = S("map", "Read schema, domains and CRS.", "layer_name:string!"),
            ["find_fields"] = S("map", "Resolve actual field names and aliases before querying values.", "search_term:string! layer_name:string"),
            ["get_selection_summary"] = S("map", "Read current selected counts by layer; do not change selection."),
            ["get_all_selections"] = S("map", "Read bounded identifying previews of current selections; preserves selection."),
            ["get_selection"] = S("map", "Read selected attributes from a named layer.", "layer_name:string! max_features:int"),
            ["resolve_analytics_plan"] = S("map", "Resolve layer/field/geography refs for counts and length. Use before summary; inspect plan_complete.", "asset_term:string! year:string group_concepts:strings geography_term:string"),
            ["profile_fields"] = S("map", "Read nulls, distinct values, duplicates and coded domains; inspect scan completeness.", "layer_name:string! fields:strings! top_values:int"),
            ["query_layer_data"] = S("map", "Read bounded rows or count/distinct/group_by. No raw SQL. Use structured summarize_layer filters for filtered aggregates.", "layer_name:string! action:string! field_name:string fields:strings limit:int max_groups:int"),
            ["summarize_layer"] = S("map", "Count and measure actual geometry using discovered fields. Structured filters and group_fields; preserves definition query.", "layer_name:string! filters:filters group_fields:strings max_groups:int"),
            ["spatial_summary"] = S("map", "Count/clip/measure by reference geography. Inspect clipping, units, filters, truncation and completeness.", "target_layer:string! geography_layer:string! geography_field:string geography_value:string filters:filters group_fields:strings max_groups:int"),
            ["list_geodatabases"] = S("workspace", "List the SDK's approved file geodatabases."),
            ["catalog_geodatabase"] = S("workspace", "Read approved geodatabase catalog.", "workspace:string!"),
            ["find_workspace_datasets"] = S("workspace", "Find datasets in approved GDB roots.", "search_term:string! max_results:int"),
            ["find_project_field_sources"] = S("workspace", "Read exact field sources across the open project. SDK may persist a metadata cache outside GIS data.", "field_name:string!"),
            ["describe_workspace_dataset"] = S("workspace", "Read approved dataset schema/count/CRS.", "workspace:string! dataset:string!"),
            ["query_workspace_dataset"] = S("workspace", "Read approved dataset using count/sample/distinct/group_by and structured filters; no SQL.", "workspace:string! dataset:string! action:string! fields:strings filters:filters limit:int max_groups:int"),
            ["compare_workspace_datasets"] = S("workspace", "Compare schema and counts, not feature equivalence.", "workspace_a:string! dataset_a:string! workspace_b:string! dataset_b:string!"),
            ["find_utility_networks"] = S("workspace", "Read available Utility Network datasets."),
            ["describe_utility_network"] = S("workspace", "Read UN schema and terminal configurations; never validate topology.", "workspace:string! utility_network:string!"),
            ["summarize_un_asset_classifications"] = S("workspace", "Read decoded asset classes and counts in named map; default TCW_UtilityNetwork.", "map_name:string layer_names:strings"),
            ["summarize_un_device_terminals"] = S("workspace", "Read device terminals and line-end assignments; no hydraulic flow inference.", "map_name:string device_layer_name:string line_layer_name:string"),
            ["audit_un_preview_ids"] = S("workspace", "Read null/blank/duplicate Preview IDs.", "map_name:string layer_names:strings"),
            ["reconcile_area1_controlled_load"] = S("workspace", "Read and compare the Area 1 contract against live data; never load data.", "map_name:string"),
            ["audit_un_connectivity_topology"] = S("workspace", "Read topology/dirty-area/connectivity evidence. Does not validate or alter topology.", "map_name:string"),
            ["diagnose_un_connectivity_relationship"] = S("workspace", "Read digitized FROM/TO relationship evidence and bounded trace results; never edit or infer flow direction.", "map_name:string line_tcw_preview_id:string! line_end:string! target_tcw_preview_id:string"),
            ["get_ground_elevation"] = S("elevation", "Read qualified DEM ground elevation for exact asset ID. Ground is not pipe elevation.", "asset_id:string! map_name:string layer_name:string"),
            ["get_elevation_profile"] = S("elevation", "Read qualified ground profile along exact line ID; endpoints are digitization, not flow.", "line_tcw_preview_id:string! map_name:string layer_name:string spacing_ft:number max_samples:int")
        };

        internal static void Validate(string name, JsonElement args)
        {
            if (!Tools.TryGetValue(name ?? "", out Spec spec))
                throw new InvalidOperationException("Tool is not in the read-only allowlist.");
            if (args.ValueKind != JsonValueKind.Object)
                throw new InvalidOperationException("Arguments must be an object.");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (JsonProperty p in args.EnumerateObject())
            {
                if (!seen.Add(p.Name) || !spec.Parameters.TryGetValue(p.Name, out string declared))
                    throw new InvalidOperationException("Unknown or duplicate argument: " + p.Name);
                string type = declared.TrimEnd('!');
                bool valid = type switch
                {
                    "string" => p.Value.ValueKind == JsonValueKind.String && p.Value.GetString().Length <= 512,
                    "int" => p.Value.TryGetInt32(out int intValue) && intValue >= 1 && intValue <= 100,
                    "number" => p.Value.TryGetDouble(out double doubleValue) && double.IsFinite(doubleValue) && doubleValue > 0 && doubleValue <= 10000,
                    "strings" => p.Value.ValueKind == JsonValueKind.Array && p.Value.GetArrayLength() <= 20 && p.Value.EnumerateArray().All(v => v.ValueKind == JsonValueKind.String && v.GetString().Length <= 256),
                    "filters" => ValidFilters(p.Value),
                    _ => false
                };
                if (!valid) throw new InvalidOperationException("Invalid or oversized argument: " + p.Name);
                if ((p.Name == "group_fields" || p.Name == "group_concepts") && p.Value.GetArrayLength() > 4)
                    throw new InvalidOperationException("At most four grouping concepts/fields are permitted.");
                if (p.Name == "fields" && name == "profile_fields" && p.Value.GetArrayLength() > 10)
                    throw new InvalidOperationException("At most ten fields can be profiled.");
                if (p.Name == "fields" && name == "query_workspace_dataset" && p.Value.GetArrayLength() > 4)
                    throw new InvalidOperationException("At most four workspace fields can be queried.");
            }
            foreach (var p in spec.Parameters.Where(p => p.Value.EndsWith('!')))
                if (!args.TryGetProperty(p.Key, out JsonElement v) || (v.ValueKind == JsonValueKind.String && string.IsNullOrWhiteSpace(v.GetString())))
                    throw new InvalidOperationException("Missing argument: " + p.Key);
            if (args.TryGetProperty("action", out JsonElement action))
            {
                string[] allowed = name == "query_workspace_dataset"
                    ? new[] { "count", "sample", "distinct", "group_by" }
                    : new[] { "count", "query", "distinct", "group_by" };
                if (!allowed.Contains(action.GetString(), StringComparer.Ordinal))
                    throw new InvalidOperationException("Unsupported read action.");
            }
            if (args.TryGetProperty("line_end", out JsonElement end) && end.GetString() != "FROM" && end.GetString() != "TO")
                throw new InvalidOperationException("line_end must be FROM or TO.");
        }

        private static bool ValidFilters(JsonElement value)
        {
            if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() > 4) return false;
            string[] operators = { "equals", "not_equals", "gt", "gte", "lt", "lte", "contains", "is_null", "not_null", "year_equals" };
            foreach (JsonElement filter in value.EnumerateArray())
            {
                if (filter.ValueKind != JsonValueKind.Object) return false;
                var names = new HashSet<string>();
                foreach (JsonProperty p in filter.EnumerateObject())
                    if (!names.Add(p.Name) || !new[] { "field", "operator", "value" }.Contains(p.Name) || p.Value.ValueKind != JsonValueKind.String || p.Value.GetString().Length > 512) return false;
                if (!filter.TryGetProperty("field", out JsonElement field) || string.IsNullOrWhiteSpace(field.GetString()) ||
                    !filter.TryGetProperty("operator", out JsonElement op) || !operators.Contains(op.GetString())) return false;
                if (op.GetString() != "is_null" && op.GetString() != "not_null" && !filter.TryGetProperty("value", out _)) return false;
            }
            return true;
        }

        internal static Task<string> ExecuteAsync(string name, JsonElement args, CancellationToken cancellationToken)
        {
            Validate(name, args); // Mandatory second boundary, even for an internal caller.
            cancellationToken.ThrowIfCancellationRequested();
            return Tools[name].Service switch
            {
                "map" => ArcGisToolService.ExecuteAsync(name, args),
                "workspace" => TcwGdbWorkspaceService.ExecuteAsync(name, args),
                "elevation" => ElevationToolService.ExecuteAsync(name, args, cancellationToken),
                _ => throw new InvalidOperationException("Unapproved service.")
            };
        }
    }
}
