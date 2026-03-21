"""
Router classification eval — tests which model best classifies user input
into the correct task type (log_classify, code_review, doc_extract).

Runs all 150 test prompts (50 per task) against each model once.
Ground truth is derived from which JSON file the prompt came from.

Usage:
    python -m benchmark.router_eval
    python -m benchmark.router_eval --model llama3.2
"""

import argparse
import csv
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import MODELS, OLLAMA_URL, RESULTS_DIR, TEST_PROMPTS_DIR, DEFAULT_TEMPERATURE, MAX_RETRIES
from schemas.router import RouterDecision

TASK_FILES = {
    "log_classify": "log_classify.json",
    "code_review":  "code_review.json",
    "doc_extract":  "doc_extract.json",
}

SYSTEM_PROMPT = (
    "You are a task router. Given a user request, classify it into exactly one "
    "of the following task types:\n"
    "  - log_classify : the input is a server/application log line or log snippet\n"
    "  - code_review  : the input is source code that needs review or analysis\n"
    "  - doc_extract  : the input is a document, invoice, or form to extract metadata from\n\n"
    "Respond with a JSON object matching this schema:\n"
    "  task_type   : one of 'log_classify', 'code_review', 'doc_extract'\n"
    "  confidence  : float between 0.0 and 1.0\n"
    "  reasoning   : one sentence explaining your classification\n\n"
    "Return only the JSON object, nothing else."
)

CSV_FIELDS = [
    "run_id",
    "model",
    "prompt_id",
    "category",
    "ground_truth",
    "predicted",
    "correct",
    "confidence",
    "valid_schema",
    "retry_count",
    "ttft_ms",
    "tokens_per_sec",
    "total_ms",
    "error",
]


def load_labeled_prompts() -> list[dict]:
    """Load all prompts from all task files and attach ground_truth label."""
    prompts = []
    for task, filename in TASK_FILES.items():
        path = Path(TEST_PROMPTS_DIR) / filename
        if not path.exists():
            print(f"[router_eval] Missing prompt file: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            for item in json.load(f):
                prompts.append({
                    "id":           item["id"],
                    "category":     item["category"],
                    "input":        item["input"],
                    "ground_truth": task,
                })
    return prompts


def results_path(model: str) -> Path:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = model.replace(":", "-")
    filename = f"router_eval__{safe_model}__{timestamp}.csv"
    return Path(RESULTS_DIR) / filename


def call_ollama(
    model: str, user_input: str
) -> tuple[str | None, float | None, float | None, float | None]:
    """Call Ollama with the routing system prompt. Returns (raw, ttft_ms, tok/s, total_ms)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_input},
        ],
        "format":  "json",
        "options": {"temperature": DEFAULT_TEMPERATURE},
        "stream":  True,
    }

    ttft_ms = None
    total_content = []
    token_count = 0
    start = time.perf_counter()

    try:
        with httpx.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                if content:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - start) * 1000
                    total_content.append(content)
                if chunk.get("done"):
                    token_count = chunk.get("eval_count", 0)
                    break

    except Exception as e:
        print(f"[router_eval] Ollama call failed: {type(e).__name__}: {e}")
        return None, None, None, None

    total_ms = (time.perf_counter() - start) * 1000
    raw = "".join(total_content)
    generation_ms = total_ms - (ttft_ms or 0)
    tokens_per_sec = (
        round(token_count / (generation_ms / 1000), 2)
        if generation_ms > 0 else None
    )
    return raw, round(ttft_ms, 2) if ttft_ms else None, tokens_per_sec, round(total_ms, 2)


def classify_with_retry(
    model: str, user_input: str
) -> tuple[RouterDecision | None, int, float | None, float | None, float | None, str | None]:
    """
    Call the model and validate against RouterDecision schema.
    Retries up to MAX_RETRIES times on validation failure.
    Returns (decision, retry_count, ttft_ms, tok/s, total_ms, error).
    """
    prompt = user_input
    retry_count = 0
    last_error = None
    ttft_ms = tokens_per_sec = total_ms = None

    while retry_count <= MAX_RETRIES:
        if last_error and retry_count > 0:
            prompt = (
                f"{user_input}\n\n"
                f"Your previous attempt failed validation:\n"
                f"{last_error}\n"
                f"Try again."
            )

        raw, ttft_ms, tokens_per_sec, total_ms = call_ollama(model, prompt)

        if raw is None:
            return None, retry_count, ttft_ms, tokens_per_sec, total_ms, "Ollama call failed"

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"Response was not valid JSON: {e}"
            retry_count += 1
            continue

        try:
            decision = RouterDecision(**data)
            return decision, retry_count, ttft_ms, tokens_per_sec, total_ms, None
        except ValidationError as e:
            errors = [
                f"  - {'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ]
            last_error = "\n".join(errors)
            retry_count += 1

    return None, MAX_RETRIES, ttft_ms, tokens_per_sec, total_ms, last_error


def run_eval(model: str) -> Path:
    prompts = load_labeled_prompts()
    out_path = results_path(model)
    total = len(prompts)

    print(f"\n{'='*60}")
    print(f"  model:   {model}")
    print(f"  prompts: {total}  (50 per task, 1 run each)")
    print(f"  output:  {out_path}")
    print(f"{'='*60}\n")

    with open(out_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for i, prompt in enumerate(prompts, 1):
            decision, retry_count, ttft_ms, tokens_per_sec, total_ms, error = (
                classify_with_retry(model, prompt["input"])
            )

            valid_schema = decision is not None
            predicted    = decision.task_type if decision else None
            confidence   = decision.confidence if decision else None
            correct      = predicted == prompt["ground_truth"] if predicted else False

            row = {
                "run_id":         str(uuid.uuid4())[:8],
                "model":          model,
                "prompt_id":      prompt["id"],
                "category":       prompt["category"],
                "ground_truth":   prompt["ground_truth"],
                "predicted":      predicted or "",
                "correct":        correct,
                "confidence":     round(confidence, 3) if confidence is not None else "",
                "valid_schema":   valid_schema,
                "retry_count":    retry_count,
                "ttft_ms":        ttft_ms or "",
                "tokens_per_sec": tokens_per_sec or "",
                "total_ms":       total_ms or "",
                "error":          error or "",
            }
            writer.writerow(row)
            csvfile.flush()

            status = "ok" if correct else ("SCHEMA_FAIL" if not valid_schema else "WRONG")
            retries = f" (retries: {retry_count})" if retry_count else ""
            print(
                f"  [{i:>3}/{total}] {prompt['id']:<8} "
                f"gt={prompt['ground_truth']:<15} "
                f"pred={predicted or 'None':<15} "
                f"{status}{retries}"
            )

    print(f"\nDone. Results saved to: {out_path}\n")
    return out_path


def print_summary(out_path: Path) -> None:
    rows = []
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return

    model = rows[0]["model"]
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"] == "True")
    valid   = sum(1 for r in rows if r["valid_schema"] == "True")

    def avg(values):
        vals = [float(v) for v in values if v not in ("", None)]
        return round(sum(vals) / len(vals), 2) if vals else None

    print(f"{'='*60}")
    print(f"  SUMMARY — {model}")
    print(f"{'='*60}")
    print(f"  Total prompts:    {total}")
    print(f"  Correct:          {correct}/{total} ({100*correct//total}%)")
    print(f"  Valid schema:     {valid}/{total} ({100*valid//total}%)")
    print(f"  Avg tok/s:        {avg(r['tokens_per_sec'] for r in rows)}")
    print(f"  Avg TTFT:         {avg(r['ttft_ms'] for r in rows)} ms")
    print(f"  Avg confidence:   {avg(r['confidence'] for r in rows)}")

    # accuracy per task
    tasks = ["log_classify", "code_review", "doc_extract"]
    print(f"\n  Accuracy by task:")
    for task in tasks:
        task_rows = [r for r in rows if r["ground_truth"] == task]
        task_correct = sum(1 for r in task_rows if r["correct"] == "True")
        print(f"    {task:<15} {task_correct}/{len(task_rows)}")

    # accuracy per category
    categories = sorted(set(r["category"] for r in rows))
    print(f"\n  Accuracy by category:")
    for cat in categories:
        cat_rows = [r for r in rows if r["category"] == cat]
        cat_correct = sum(1 for r in cat_rows if r["correct"] == "True")
        print(f"    {cat:<12} {cat_correct}/{len(cat_rows)}")

    # confusion: where did it go wrong?
    wrong = [r for r in rows if r["correct"] == "False" and r["predicted"]]
    if wrong:
        print(f"\n  Misclassifications ({len(wrong)}):")
        from collections import Counter
        confusion = Counter((r["ground_truth"], r["predicted"]) for r in wrong)
        for (gt, pred), count in confusion.most_common():
            print(f"    {gt:<15} -> {pred:<15} x{count}")

    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Evaluate models on router classification task")
    parser.add_argument(
        "--model",
        choices=list(MODELS) + ["all"],
        default="all",
        help="Model to evaluate, or 'all' (default)",
    )
    args = parser.parse_args()

    models = list(MODELS) if args.model == "all" else [args.model]

    for model in models:
        out_path = run_eval(model)
        print_summary(out_path)


if __name__ == "__main__":
    main()
