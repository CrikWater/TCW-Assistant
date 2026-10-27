"""Run REAL Ollama/RAG validation against the running local app. No model fixtures."""
import argparse
import csv
import json
import platform
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.cli import connection, call
from backend.config import ROOT

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def run_query(client, case):
    start = time.perf_counter()
    row = dict(case)
    row["executed_at"] = timestamp()
    try:
        r = call(client, "POST", "/api/ask", {"question": case["question"], "diagnostics": True})
        cited = {s["document_id"] for s in r["citations"]}
        retrieved = {s["document_id"] for s in r["retrieved_evidence"]}
        expected = set(case.get("expected_sources", []))
        row.update(execution_status="completed", answer=r["answer"], actual_status=r["status"],
            retrieved_sources=sorted(retrieved), cited_sources=sorted(cited),
            expected_sources_retrieved=expected.issubset(retrieved),
            expected_sources_cited=expected.issubset(cited),
            status_matches=r["status"] == case["expected_status"],
            key_pattern_checks={p: bool(re.search(p, r["answer"], re.I)) for p in case.get("expected_key_patterns", [])},
            retrieval_scores=[{"source": e["document_id"], "chunk": e["chunk_id"], "score": e["score"],
                               "page": e["page_number"], "section": e["section"]} for e in r["retrieved_evidence"]],
            answer_correctness="requires_human_review", citation_correctness="requires_human_entailment_review",
            refusal_passed=(r["status"] == "unknown" and not r["claims"]) if case["expected_status"] == "unknown" else None,
            metrics=r["metrics"], evidence=r["citations"])
        # The application mechanically validates exact quotes. Humans must check support/relevance.
        row["exact_quote_guard"] = "passed_for_displayed_claims" if r["claims"] else "not_applicable"
        row["automatic_checks_passed"] = (row["status_matches"] and row["expected_sources_cited"]
            and all(row["key_pattern_checks"].values()))
    except Exception as exc:
        row.update(execution_status="failed", error=str(exc), automatic_checks_passed=False,
                   answer_correctness="not_scored", citation_correctness="not_scored")
    row["client_elapsed_s"] = time.perf_counter() - start
    return row

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise-lifecycle", action="store_true")
    args = parser.parse_args()
    dataset_path = ROOT / "tests/validation_questions.json"
    if not dataset_path.is_file():
        print("BLOCKED: Supply the approved private tests/validation_questions.json on the host. "
              "District acceptance questions are not included in the public repository.", file=sys.stderr)
        return 2
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    report = {"started_at": timestamp(), "execution_host": platform.platform(),
        "benchmark_scope": "This machine only. Do not label it a Dell/T1000 run unless hardware_snapshot confirms that.",
        "questions": [], "lifecycle": {}, "human_review_complete": False}
    output_dir = ROOT / "evidence/live_validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = output_dir / f"validation_{stamp}.json"
    def checkpoint():
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    try:
        with connection() as client:
            status = call(client, "GET", "/api/status")
            report["hardware_snapshot"] = status
            if not status["ready_for_query"]:
                report.update(status="blocked", reason="Ollama/models/index not ready. No question success rate was computed.")
                checkpoint();print(str(output));return 2
            for case in dataset["questions"]:
                print(case["id"], case["question"], flush=True)
                row = run_query(client, case)
                report["questions"].append(row)
                print(row["execution_status"], row.get("actual_status", ""), flush=True)
                checkpoint()
            if args.exercise_lifecycle:
                holdout = dataset["holdout"]
                doc_id = holdout["document_id"]
                before = call(client, "GET", "/api/documents")
                # This switch explicitly permits only the designated holdout's lifecycle exercise.
                if any(d["document_id"] == doc_id and d["active"] for d in before):
                    call(client, "POST", f"/api/documents/{doc_id}/deactivate", {})
                report["lifecycle"]["before_count"] = call(client, "GET", "/api/status")["document_count"]
                unknown = {**holdout, "id": "LIVE-BEFORE", "expected_status": "unknown",
                           "expected_sources": [], "expected_key_patterns": []}
                report["lifecycle"]["before_question"] = run_query(client, unknown)
                report["lifecycle"]["ingestion"] = call(client, "POST", f"/api/corpus/{doc_id}/import", {})
                report["lifecycle"]["after_count"] = call(client, "GET", "/api/status")["document_count"]
                positive = {**holdout, "id": "LIVE-AFTER", "expected_status": "answered", "expected_sources": [doc_id]}
                report["lifecycle"]["after_question"] = run_query(client, positive)
                report["lifecycle"]["duplicate"] = call(client, "POST", f"/api/corpus/{doc_id}/import", {})
                report["lifecycle"]["reindex"] = call(client, "POST", f"/api/documents/{doc_id}/reindex", {})
                report["lifecycle"]["reindex_question"] = run_query(client, positive)
                report["lifecycle"]["count_increased_by_one"] = (
                    report["lifecycle"]["after_count"] == report["lifecycle"]["before_count"] + 1)
                life = report["lifecycle"]
                life["automatic_checks_passed"] = all([
                    life["before_question"]["automatic_checks_passed"],
                    life["ingestion"]["status"] == "indexed",
                    life["count_increased_by_one"],
                    life["after_question"]["automatic_checks_passed"],
                    life["duplicate"]["status"] == "unchanged",
                    life["reindex"]["status"] == "indexed",
                    life["reindex"]["revision_id"] != life["ingestion"]["revision_id"],
                    life["reindex_question"]["automatic_checks_passed"],
                ])
                checkpoint()
            completed = [r for r in report["questions"] if r["execution_status"] == "completed"]
            times = [r["metrics"]["total_s"] for r in completed]
            report.update(status="executed_pending_human_review", completed_questions=len(completed),
                total_questions=len(report["questions"]),
                mechanical_checks_passed=sum(bool(r["automatic_checks_passed"]) for r in report["questions"]),
                semantic_correctness_rate=None,
                median_total_s=statistics.median(times) if times else None,
                ended_at=timestamp())
            report["hardware_snapshot_after"] = call(client, "GET", "/api/status")
            report["performance_medians"] = {}
            for field in ("retrieval_s", "time_to_first_content_token_s", "generation_wall_s", "tokens_per_second"):
                values = [r["metrics"][field] for r in completed if r["metrics"].get(field) is not None]
                report["performance_medians"][field] = statistics.median(values) if values else None
            checkpoint()
            with (output.with_suffix(".csv")).open("w", newline="", encoding="utf-8-sig") as f:
                keys=["id","category","question","execution_status","actual_status","expected_key_fact",
                      "answer","expected_sources_retrieved","expected_sources_cited","status_matches",
                      "answer_correctness","citation_correctness","client_elapsed_s"]
                w=csv.DictWriter(f,fieldnames=keys,extrasaction="ignore");w.writeheader();w.writerows(report["questions"])
            print(str(output))
            baseline_passed = all(r["automatic_checks_passed"] for r in report["questions"])
            lifecycle_passed = not args.exercise_lifecycle or report["lifecycle"]["automatic_checks_passed"]
            return 0 if baseline_passed and lifecycle_passed else 1
    except Exception as exc:
        report.update(status="blocked_or_interrupted", reason=str(exc), ended_at=timestamp())
        checkpoint();print(str(output));return 2

if __name__ == "__main__":
    raise SystemExit(main())
