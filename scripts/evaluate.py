"""Run ten reproducible evaluation jobs and record automated evidence only."""

import csv
import json
import sys
import time
from pathlib import Path

import requests


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    root = Path(__file__).resolve().parents[1]
    inputs = json.loads((root / "evaluation_inputs.json").read_text(encoding="utf-8"))
    output = root / "data" / "evaluation_results.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "id", "job_id", "status", "automated_checks", "human_relevance_score", "notes"
        ])
        writer.writeheader()
        for item in inputs:
            response = requests.post(
                f"{base_url}/api/v1/broll/jobs",
                json={"script": item["script"], "aspect_ratios": ["16:9"], "render": True},
                headers={"Idempotency-Key": f"evaluation-{item['id']}-v1"},
                timeout=30,
            )
            response.raise_for_status()
            job_id = response.json()["job_id"]
            for _ in range(240):
                job = requests.get(f"{base_url}/api/v1/jobs/{job_id}", timeout=10).json()
                if job["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.5)
            checks = "passed" if job["status"] == "completed" else "failed"
            writer.writerow({
                "id": item["id"], "job_id": job_id, "status": job["status"],
                "automated_checks": checks, "human_relevance_score": "",
                "notes": "Human score intentionally blank; evaluate footage relevance manually.",
            })
            handle.flush()
            print(f"{item['id']}: {job['status']} ({job_id})")
    print(f"Evaluation CSV: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
