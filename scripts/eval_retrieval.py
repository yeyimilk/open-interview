from __future__ import annotations

import argparse
import json
from pathlib import Path


def _terms_hit(text: str, terms: list[str]) -> set[str]:
    haystack = text.lower()
    return {term for term in terms if term.lower() in haystack}


def evaluate(fixtures_path: Path, results_path: Path) -> dict:
    fixtures = {case["id"]: case for case in json.loads(fixtures_path.read_text())["cases"]}
    results = json.loads(results_path.read_text())
    rows = []
    failures = []
    for result in results.get("cases", []):
        case = fixtures[result["id"]]
        expected = list(case["expected_terms"])
        chunks = result.get("chunks", [])[:3]
        relevant = 0
        found_terms: set[str] = set()
        for chunk in chunks:
            text = " ".join(
                str(chunk.get(k) or "") for k in ("title", "text", "snippet", "source")
            )
            hits = _terms_hit(text, expected)
            found_terms.update(hits)
            if hits:
                relevant += 1
        precision = relevant / max(1, len(chunks))
        row = {
            "id": case["id"],
            "precision_at_3": round(precision, 3),
            "found_terms": sorted(found_terms),
            "missing_terms": sorted(set(expected) - found_terms),
            "pass": precision >= float(case["min_precision_at_3"]),
        }
        rows.append(row)
        if not row["pass"]:
            failures.append(row)
    return {"pass": not failures, "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Score retrieval output JSON against local fixture expectations. "
            "Results JSON format: {\"cases\":[{\"id\":...,\"chunks\":[...]},...]}"
        )
    )
    parser.add_argument(
        "--fixtures",
        default="backend/services/core/tests/fixtures/retrieval_eval.json",
    )
    parser.add_argument("--results", required=True)
    args = parser.parse_args()
    report = evaluate(Path(args.fixtures), Path(args.results))
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
