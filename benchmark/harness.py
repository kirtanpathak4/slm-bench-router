"""
Benchmark harness - BENCHMARK mode only.
Runs a specific model + task combo across all 50 test prompts, 5 runs each.
Router mode is handled separately via the API.

Usage:
    python -m benchmark.harness --task log_classify --model llama3.2
    python -m benchmark.harness --task code_review --model phi4-mini
    python -m benchmark.harness --task doc_extract --model qwen2.5:3b
    python -m benchmark.harness --task all --model all
"""

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# allow running as: python -m benchmark.harness from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import (
    CodeReviewAgent,
    DocExtractorAgent,
    LogClassifierAgent,
)
from config import BENCHMARK_RUNS, MODELS, RESULTS_DIR, TEST_PROMPTS_DIR

TASK_MAP = {
    "log_classify": LogClassifierAgent,
    "code_review": CodeReviewAgent,
    "doc_extract": DocExtractorAgent,
}

PROMPT_FILES = {
    "log_classify": "log_classify.json",
    "code_review": "code_review.json",
    "doc_extract": "doc_extract.json",
}

CSV_FIELDS = [
    "run_id",
    "task",
    "model",
    "prompt_id",
    "category",
    "run_number",
    "cold_start",
    "success",
    "retry_count",
    "ttft_ms",
    "tokens_per_sec",
    "total_ms",
    "error",
]


def load_prompts(task: str) -> list[dict]:
    path = Path(TEST_PROMPTS_DIR) / PROMPT_FILES[task]
    if not path.exists():
        print(f"[harness] Test prompt file not found: {path}", file=sys.stderr)
        print(f"[harness] Run from the project root and ensure the file exists.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def results_path(task: str, model: str) -> Path:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = model.replace(":", "-")
    filename = f"{task}__{safe_model}__{timestamp}.csv"
    return Path(RESULTS_DIR) / filename


def run_benchmark(task: str, model: str) -> Path:
    agent_cls = TASK_MAP[task]
    agent = agent_cls(model=model)
    prompts = load_prompts(task)
    out_path = results_path(task, model)

    total = len(prompts) * BENCHMARK_RUNS
    done = 0

    print(f"\n{'='*60}")
    print(f"  task:   {task}")
    print(f"  model:  {model}")
    print(f"  prompts: {len(prompts)}  runs each: {BENCHMARK_RUNS}  total calls: {total}")
    print(f"  output: {out_path}")
    print(f"{'='*60}\n")

    with open(out_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()

        first_call = True  # only the very first call of the session is a true cold start
        for prompt in prompts:
            prompt_id = prompt["id"]
            category = prompt["category"]
            user_input = prompt["input"]

            for run_number in range(1, BENCHMARK_RUNS + 1):
                cold_start = first_call
                first_call = False
                result = agent.run(user_input=user_input, cold_start=cold_start)

                row = {
                    "run_id": str(uuid.uuid4())[:8],
                    "task": task,
                    "model": model,
                    "prompt_id": prompt_id,
                    "category": category,
                    "run_number": run_number,
                    "cold_start": cold_start,
                    "success": result.success,
                    "retry_count": result.retry_count,
                    "ttft_ms": result.ttft_ms,
                    "tokens_per_sec": result.tokens_per_sec,
                    "total_ms": result.total_ms,
                    "error": result.error or "",
                }
                writer.writerow(row)
                csvfile.flush()

                done += 1
                status = "ok" if result.success else "FAIL"
                retries = f" (retries: {result.retry_count})" if result.retry_count else ""
                cold = " [cold]" if cold_start else ""
                total_ms_str = f"{result.total_ms:.0f}ms" if result.total_ms is not None else "n/a"
                print(
                    f"  [{done:>4}/{total}] {prompt_id} run {run_number}{cold} "
                    f"-> {status}{retries}  "
                    f"{total_ms_str}  {result.tokens_per_sec if result.tokens_per_sec is not None else 'n/a'} tok/s"
                )

    print(f"\nDone. Results saved to: {out_path}\n")
    return out_path


def print_summary(out_path: Path) -> None:
    rows = []
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return

    total = len(rows)
    passed = sum(1 for r in rows if r["success"] == "True")
    cold = [r for r in rows if r["cold_start"] == "True"]
    warm = [r for r in rows if r["cold_start"] == "False"]

    def avg(values):
        vals = []
        for v in values:
            if v == "":
                continue
            try:
                vals.append(float(v))
            except (ValueError, TypeError):
                pass  # skip malformed CSV cells
        return round(sum(vals) / len(vals), 2) if vals else None

    print(f"{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Total runs:       {total}")
    print(f"  Passed:           {passed} ({100*passed//total if total else 0}%)")
    print(f"  Failed:           {total - passed}")
    print(f"  Avg total_ms:     {avg(r['total_ms'] for r in rows)} ms")
    print(f"  Avg tok/s:        {avg(r['tokens_per_sec'] for r in rows)}")
    print(f"  Avg TTFT (cold):  {avg(r['ttft_ms'] for r in cold)} ms")
    print(f"  Avg TTFT (warm):  {avg(r['ttft_ms'] for r in warm)} ms")

    # per-category breakdown
    categories = sorted(set(r["category"] for r in rows))
    print(f"\n  By category:")
    for cat in categories:
        cat_rows = [r for r in rows if r["category"] == cat]
        cat_passed = sum(1 for r in cat_rows if r["success"] == "True")
        print(f"    {cat:<12} {cat_passed}/{len(cat_rows)} passed")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Run benchmark harness")
    parser.add_argument(
        "--task",
        choices=list(TASK_MAP.keys()) + ["all"],
        required=True,
        help="Task to benchmark, or 'all' to run every task",
    )
    parser.add_argument(
        "--model",
        choices=list(MODELS) + ["all"],
        required=True,
        help="Model to use, or 'all' to run every model",
    )
    args = parser.parse_args()

    tasks = list(TASK_MAP.keys()) if args.task == "all" else [args.task]
    models = list(MODELS) if args.model == "all" else [args.model]

    for task in tasks:
        for model in models:
            out_path = run_benchmark(task, model)
            print_summary(out_path)


if __name__ == "__main__":
    main()
