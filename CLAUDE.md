# slm-bench-router

## Project Summary
Benchmark platform for local SLMs via Ollama. Three specialized agents + one router agent.
Measures inference speed, schema validity, and model comparison across tasks.
Not a user-facing assistant — this is an engineering testbed.

## Tech Stack
- Python 3.11+
- Ollama (local model runtime)
- FastAPI
- Pydantic v2
- pandas (benchmark results)
- Jupyter (analysis notebook)

## Models
- llama3.2 (3B)
- phi4-mini
- mistral (7B)

## Project Structure
```
slm-bench-router/
├── schemas/          # Pydantic output contracts (done)
├── agents/           # base_agent + 3 specialized + router
├── benchmark/        # harness.py + test_prompts/ + results/
├── api/              # FastAPI app
├── analysis/         # compare.ipynb
├── config.py
├── requirements.txt
└── .gitignore
```

## Agents
- LogClassifierAgent   → LogClassification schema
- CodeReviewAgent      → CodeReviewResult schema
- DocExtractorAgent    → DocumentMetadata schema
- RouterAgent          → RouterDecision schema (built last, after benchmarks)

## Key Architecture Decisions
- All agents use Ollama `format: "json"` (grammar-constrained) — no prompt-only strategy
- Every agent inherits from BaseAgent (retry + validation + confidence)
- Max 2 retries per call; on failure, error is fed back to model in next prompt
- Router is built LAST, informed by benchmark findings — not before

## Benchmark Design
- 50 test prompts per task, split into 4 categories:
  - Clear cut (15): should pass every model easily
  - Ambiguous (15): where models diverge
  - Edge cases (10): malformed/incomplete input
  - Negative (10): not an anomaly/issue — tests false positive rate
- 5 runs per prompt per model
- Run 1 = cold_start: true, runs 2-5 = cold_start: false
- Metrics per run: ttft_ms, tokens_per_sec, total_ms, valid_schema, retry_count, cold_start

## Benchmark Modes
- BENCHMARK mode: bypasses router, runs specific model + agent combo, saves to CSV
- ROUTER mode: RouterAgent picks task type + best model, returns result to user

## Build Order
1. schemas/          (done)
2. agents/base_agent.py
3. agents/ specialized (log, code, doc)
4. benchmark/test_prompts/
5. benchmark/harness.py
6. analysis/compare.ipynb  (after running harness)
7. agents/router_agent.py  (after analysis findings)
8. api/

## Commands
```bash
# start ollama
ollama serve

# pull models
ollama pull llama3.2
ollama pull phi4-mini
ollama pull mistral

# run benchmark
python -m benchmark.harness --task log_classify --model llama3.2

# run api
uvicorn api.main:app --reload
```

## Ollama API
- Base URL: http://localhost:11434
- Chat endpoint: POST /api/chat
- Models list: GET /api/tags

## What NOT to Do
- Do not add memory footprint measurement to main harness (adds noise, unreliable on Windows)
- Do not test prompt-only vs grammar-constrained (decision made: always use grammar-constrained)
- Do not build router before benchmark analysis is done
- Do not add more than 3 task agents (scope creep)
