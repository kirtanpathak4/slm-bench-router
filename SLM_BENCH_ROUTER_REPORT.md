# slm-bench-router: Project Report

A benchmark platform for evaluating local Small Language Models (SLMs) through Ollama.
Three specialized agents + one router agent. Measures inference speed, schema validity,
and model comparison across tasks. This is an engineering testbed, not a user-facing assistant.

---

## Table of Contents

1. [Tech Stack and Why](#tech-stack-and-why)
2. [Project Structure](#project-structure)
3. [Models](#models)
4. [Schemas (Output Contracts)](#schemas-output-contracts)
5. [Agent System](#agent-system)
6. [Router Agent](#router-agent)
7. [Benchmark System](#benchmark-system)
8. [API Endpoints](#api-endpoints)
9. [Execution Flow (Visual)](#execution-flow-visual)
10. [Dry Runs (All 4 API Requests)](#dry-runs-all-4-api-requests)
11. [Special Cases and Edge Cases](#special-cases-and-edge-cases)
12. [Benchmark Results Summary](#benchmark-results-summary)
13. [Configuration Reference](#configuration-reference)
14. [Command Reference](#command-reference)

---

## Tech Stack and Why

| Technology | Version | Why |
|---|---|---|
| Python | 3.11+ | Native type unions (`str | None`), performance improvements, broad library support |
| Ollama | latest | Local-only model runtime. No API keys, no cloud, no latency. Models run on your hardware |
| FastAPI | >= 0.110 | Auto-generates OpenAPI docs (Swagger UI), async support, Pydantic integration built-in |
| Pydantic v2 | >= 2.0 | Schema validation with `model_dump()`, Literal types for enum enforcement, 5-50x faster than v1 |
| httpx | >= 0.27 | Streaming HTTP client for Ollama. Needed for TTFT measurement (first token timing via stream) |
| pandas | >= 2.0 | CSV aggregation and analysis in the Jupyter notebook |
| matplotlib | >= 3.8 | Benchmark visualization charts (speed, validity, TTFT, category breakdown) |
| Jupyter | >= 1.0 | Interactive analysis notebook for exploring benchmark results |

**Why not LangChain / LlamaIndex?** Unnecessary abstraction. Direct HTTP to Ollama is simpler,
faster, and gives full control over streaming, retries, and metrics. No middleware overhead.

**Why not OpenAI API format?** Ollama has its own `/api/chat` endpoint. Using it directly
avoids compatibility layers and gives access to Ollama-specific fields like `eval_count`.

---

## Project Structure

```
slm-bench-router/
|
|-- config.py                         # all tunable knobs in one place
|
|-- schemas/                          # Pydantic output contracts (what models must return)
|   |-- __init__.py                   #   exports all schemas
|   |-- log_classification.py         #   LogClassification
|   |-- code_review.py                #   CodeReviewResult
|   |-- doc_extraction.py             #   DocumentMetadata
|   |-- router.py                     #   RouterDecision
|
|-- agents/                           # agent implementations (inherit from BaseAgent)
|   |-- __init__.py                   #   exports all agents
|   |-- base_agent.py                 #   BaseAgent + AgentResult (retry, validation, metrics)
|   |-- log_classifier_agent.py       #   LogClassifierAgent
|   |-- code_review_agent.py          #   CodeReviewAgent
|   |-- doc_extractor_agent.py        #   DocExtractorAgent
|   |-- router_agent.py               #   RouterAgent (classify + dispatch)
|
|-- benchmark/                        # testing and evaluation
|   |-- __init__.py
|   |-- harness.py                    #   main benchmark runner (50 prompts x 5 runs x N models)
|   |-- router_eval.py                #   router classification accuracy eval
|   |-- test_prompts/                 #   150 labeled test cases
|   |   |-- log_classify.json         #     50 prompts for log classification
|   |   |-- code_review.json          #     50 prompts for code review
|   |   |-- doc_extract.json          #     50 prompts for document extraction
|   |-- results/                      #   output CSVs and PNG charts
|       |-- *.csv                     #     12 benchmark + 3 router eval CSVs
|       |-- *.png                     #     4 analysis charts
|
|-- api/                              # FastAPI service
|   |-- __init__.py
|   |-- main.py                       #   app setup, /health, /models endpoints
|   |-- routes/
|       |-- __init__.py
|       |-- infer.py                  #   POST /infer (router mode)
|       |-- benchmark.py              #   POST /benchmark (manual mode)
|
|-- analysis/
|   |-- compare.ipynb                 #   Jupyter notebook for benchmark visualization
|
|-- requirements.txt
|-- .gitignore
|-- CLAUDE.md                         #   project guidelines and architecture decisions
```

---

## Models

Three models from three different companies, ensuring architectural diversity:

| Model | Params | Company | Size on Disk | Role |
|---|---|---|---|---|
| llama3.2 | 3B | Meta | ~1.9 GB | Best for code_review (100% accuracy, 8.84 tok/s) |
| phi4-mini | 3.8B | Microsoft | ~2.5 GB | Router model (94% classification accuracy) |
| qwen2.5:3b | 3B | Alibaba | ~1.9 GB | Best for log_classify + doc_extract |

**Why these three?**
- Different training philosophies (Meta's general-purpose, Microsoft's reasoning, Alibaba's multilingual)
- All fit in RAM simultaneously without paging (~6.3 GB total)
- 3B parameter range keeps inference fast on consumer hardware

**Rejected models:**
- mistral (7B): replaced by qwen2.5:3b (smaller, faster, better accuracy)
- qwen2.5:7b: caused RAM paging (4.7 GB alone), dropped to 0.08 tok/s under pressure
- deepseek-r1: verbose chain-of-thought conflicts with `format: "json"` grammar constraint

---

## Schemas (Output Contracts)

Every model response is validated against a Pydantic v2 schema. If validation fails,
the error is fed back to the model and it retries (max 2 retries).

### LogClassification

Captures what went wrong in a server log line -- the type of system affected, how bad it is,
how certain the model is, and a human-readable explanation.

| Field | What it captures | Example value |
|---|---|---|
| `anomaly_type` | Which subsystem the error belongs to | `"database"` |
| `severity` | How urgent the issue is | `"high"` |
| `confidence` | Model's certainty (0 = guessing, 1 = certain) | `0.92` |
| `explanation` | Plain English description of what happened | `"Connection pool exhausted on primary DB host"` |

```json
{
  "anomaly_type": "database",
  "severity": "high",
  "confidence": 0.92,
  "explanation": "Connection pool exhausted on db-primary-01, indicating the database is unreachable"
}
```

### CodeReviewResult

Captures a single code issue -- what category of problem it is, how severe, where it is in
the file, what to do about it, and how confident the model is.

| Field | What it captures | Example value |
|---|---|---|
| `issue_type` | Category of the code problem | `"security"` |
| `severity` | How critical the fix is | `"critical"` |
| `line_number` | Line where the issue occurs (`null` if not determinable) | `1` |
| `suggestion` | Concrete fix recommendation | `"Use parameterized queries to prevent SQL injection"` |
| `confidence` | Model's certainty in the finding | `0.98` |

```json
{
  "issue_type": "security",
  "severity": "critical",
  "line_number": 1,
  "suggestion": "Use parameterized queries -- replace f-string interpolation with db.query('SELECT * FROM users WHERE id=?', [id])",
  "confidence": 0.98
}
```

### DocumentMetadata

Extracts structured metadata from unstructured document text -- who is involved, key dates,
what each party is obligated to do, and how confident the extraction is.

| Field | What it captures | Example value |
|---|---|---|
| `title` | Document title (`null` if not found, `""` is rejected) | `"Service Agreement"` |
| `parties` | All named parties in the document | `["Acme Corp", "Client LLC"]` |
| `dates` | All dates mentioned (any format) | `["2026-04-01", "January 15 2026"]` |
| `key_obligations` | What each party must do | `["Vendor delivers by April 1", "Client pays within 30 days"]` |
| `confidence` | Model's certainty in the extraction | `0.85` |

```json
{
  "title": "Software Service Agreement",
  "parties": ["Acme Corp", "Client LLC"],
  "dates": ["2026-04-01", "2026-01-15"],
  "key_obligations": [
    "Acme Corp will deliver the platform by April 1 2026",
    "Client LLC will pay invoice within 30 days of delivery"
  ],
  "confidence": 0.85
}
```

### RouterDecision

Used internally by the RouterAgent to classify the user's raw input before dispatching to
a specialized agent. Never returned directly to the API caller.

| Field | What it captures | Example value |
|---|---|---|
| `task_type` | Which specialized agent should handle this | `"log_classify"` |
| `reasoning` | Why the model chose this task type | `"Input is a server error log line with ERROR prefix"` |
| `confidence` | Model's certainty in the classification | `0.95` |

```json
{
  "task_type": "log_classify",
  "reasoning": "Input contains [ERROR] prefix and references a host name -- consistent with server log format",
  "confidence": 0.95
}
```

---

## Agent System

### BaseAgent (the foundation)

Every agent inherits from `BaseAgent`. It handles:

1. **Ollama communication** -- streaming HTTP to `POST /api/chat`
2. **Metrics capture** -- TTFT (time to first token), tokens/sec, total wall-clock time
3. **Schema validation** -- parse JSON, validate against Pydantic schema
4. **Retry with feedback** -- on validation failure, feed error back to model and retry

```
BaseAgent.run(user_input)
    |
    v
_call_ollama(prompt)  --->  Ollama /api/chat (streaming)
    |                              |
    |                        first token arrives --> record TTFT
    |                        ...tokens stream...
    |                        "done": true --> record eval_count, total_ms
    |
    v
_validate(raw_json)  --->  json.loads() --> Schema(**data)
    |
    |-- success? --> return AgentResult(success=True, data=...)
    |
    |-- validation error?
    |       |
    |       v
    |   retry_count < MAX_RETRIES?
    |       |-- yes --> append error to prompt, retry _call_ollama()
    |       |-- no  --> return AgentResult(success=False, error=...)
```

### AgentResult (what every agent returns)

```python
class AgentResult(BaseModel):
    success:        bool           # did validation pass?
    data:           dict | None    # validated output (model_dump)
    error:          str | None     # error message if failed
    retry_count:    int            # 0, 1, or 2
    ttft_ms:        float | None   # time to first token (milliseconds)
    tokens_per_sec: float | None   # generation speed
    total_ms:       float | None   # total wall-clock time
    cold_start:     bool           # first call of session?
```

### Metrics Calculation

```
tokens_per_sec = eval_count / ((total_ms - ttft_ms) / 1000)

where:
  eval_count   = actual token count from Ollama's response
  total_ms     = wall-clock time from request start to "done": true
  ttft_ms      = wall-clock time from request start to first content token
```

### Specialized Agents

Each specialized agent only defines two things: a `system_prompt` and a `schema`.
All execution logic is inherited from BaseAgent.

| Agent | System Prompt Summary | Schema |
|---|---|---|
| LogClassifierAgent | Classify log lines by anomaly type and severity | LogClassification |
| CodeReviewAgent | Find the single most significant issue in code | CodeReviewResult |
| DocExtractorAgent | Extract metadata from documents/invoices/forms | DocumentMetadata |

---

## Router Agent

The RouterAgent is special. It does two things in sequence:

### Step 1: Classify the input

Using `ROUTER_MODEL` (phi4-mini), classify what type of task the user input represents.

```
User input: "[ERROR] Connection pool exhausted..."
                |
                v
        phi4-mini classifies
                |
                v
RouterDecision:
    task_type: "log_classify"
    confidence: 0.95
    reasoning: "Input is a server error log line"
```

### Step 2: Dispatch to best model

Look up `ROUTER_MODEL_MAP` to find the benchmark-proven best model for that task,
then run the specialized agent.

```
task_type = "log_classify"
             |
             v
    ROUTER_MODEL_MAP["log_classify"] = "qwen2.5:3b"
             |
             v
    LogClassifierAgent(model="qwen2.5:3b").run(user_input)
             |
             v
    AgentResult with classification data
```

### Why phi4-mini for routing?

Tested all 3 models on 150 labeled prompts:

| Model | Accuracy | tok/s | Schema Validity |
|---|---|---|---|
| phi4-mini | 94.0% | 6.83 | 99.3% |
| llama3.2 | 90.0% | 8.73 | 100.0% |
| qwen2.5:3b | 92.7% | 9.15 | 100.0% |

phi4-mini won on accuracy (94%). The routing call is a simple classification --
speed matters less here because it adds fixed latency, and accuracy matters most
(a wrong classification sends the input to the wrong agent entirely).

### RouterAgent System Prompt

This prompt is identical in both `router_agent.py` and `router_eval.py`.
Changing it would invalidate the 94% accuracy measurement.

```
You are a task router. Given a user request, classify it into exactly one
of the following task types:
  - log_classify : the input is a server/application log line or log snippet
  - code_review  : the input is source code that needs review or analysis
  - doc_extract  : the input is a document, invoice, or form to extract metadata from

Respond with a JSON object matching this schema:
  task_type   : one of 'log_classify', 'code_review', 'doc_extract'
  confidence  : float between 0.0 and 1.0
  reasoning   : one sentence explaining your classification

Return only the JSON object, nothing else.
```

---

## Benchmark System

### Test Prompts (150 total)

50 prompts per task, split into 4 categories:

| Category | Count | Purpose |
|---|---|---|
| clear | 15 | Unambiguous cases -- every model should pass |
| ambiguous | 15 | Borderline cases -- where models diverge |
| edge | 10 | Malformed, empty, weird formats -- stress tests |
| negative | 10 | Non-anomalies, correct code, non-contracts -- tests false positive rate |

### Benchmark Harness (harness.py)

Runs a specific model + task combo: 50 prompts x 5 runs = 250 inference calls per combo.

```
python -m benchmark.harness --task log_classify --model llama3.2
```

- Run 1 = cold_start: true (model loads into RAM)
- Runs 2-5 = cold_start: false (model already warm)
- Each row written to CSV immediately (flush after each write)
- Progress printed live: `[  42/ 250] lc_003 run 2 -> ok  1234ms  8.52 tok/s`

### Router Eval (router_eval.py)

Tests routing accuracy: 150 prompts x 1 run per model.

```
python -m benchmark.router_eval --model phi4-mini
```

- Ground truth = which JSON file the prompt came from
- Measures: accuracy, schema validity, speed, confusion matrix

### Generated Files

```
benchmark/results/
  |-- 9 task benchmark CSVs (task__model__timestamp.csv)
  |-- 3 router eval CSVs    (router_eval__model__timestamp.csv)
  |-- 4 analysis PNGs       (speed_comparison, validity_rate, ttft_cold_warm, category_breakdown)
```

---

## API Endpoints

The API has 4 endpoints across 2 modes:

| Endpoint | Method | Mode | Purpose |
|---|---|---|---|
| /health | GET | System | Server alive check |
| /models | GET | System | List models and router mapping |
| /infer | POST | Router | Auto-classify and dispatch (production use) |
| /benchmark | POST | Benchmark | Force specific task + model (testing use) |

### Swagger UI

Start the server, then open `http://localhost:8000/docs` in a browser.
Click any endpoint, click "Try it out", fill in the body, click "Execute".

---

## Execution Flow (Visual)

### Flow 1: POST /infer (Router Mode)

This is the real endpoint. User sends text, system figures out everything.

```
Client                  API                 RouterAgent            Specialized Agent      Ollama
  |                      |                      |                       |                   |
  |  POST /infer         |                      |                       |                   |
  |  {"input": "..."}    |                      |                       |                   |
  |--------------------->|                      |                       |                   |
  |                      |                      |                       |                   |
  |                      |  RouterAgent().run()  |                       |                   |
  |                      |--------------------->|                       |                   |
  |                      |                      |                       |                   |
  |                      |           Step 1: Classify input             |                   |
  |                      |                      |  POST /api/chat       |                   |
  |                      |                      |  model: phi4-mini     |                   |
  |                      |                      |  format: json         |                   |
  |                      |                      |------------------------------------------>|
  |                      |                      |                       |                   |
  |                      |                      |  <--- stream tokens --|                   |
  |                      |                      |  record TTFT          |                   |
  |                      |                      |  <--- "done": true ---|                   |
  |                      |                      |                       |                   |
  |                      |                      |  validate against     |                   |
  |                      |                      |  RouterDecision       |                   |
  |                      |                      |  schema               |                   |
  |                      |                      |                       |                   |
  |                      |           Step 2: Dispatch to best agent     |                   |
  |                      |                      |                       |                   |
  |                      |                      |  task_type =          |                   |
  |                      |                      |   "log_classify"      |                   |
  |                      |                      |                       |                   |
  |                      |                      |  model =              |                   |
  |                      |                      |   MAP["log_classify"] |                   |
  |                      |                      |   = "qwen2.5:3b"     |                   |
  |                      |                      |                       |                   |
  |                      |                      |  LogClassifierAgent   |                   |
  |                      |                      |  (model="qwen2.5:3b")|                   |
  |                      |                      |  .run(user_input)     |                   |
  |                      |                      |--------------------->|                   |
  |                      |                      |                       |  POST /api/chat   |
  |                      |                      |                       |  model: qwen2.5:3b|
  |                      |                      |                       |  format: json     |
  |                      |                      |                       |----------------->|
  |                      |                      |                       |                   |
  |                      |                      |                       |  <--- stream -----|
  |                      |                      |                       |  validate against |
  |                      |                      |                       |  LogClassification|
  |                      |                      |                       |  schema           |
  |                      |                      |                       |                   |
  |                      |                      |  <-- AgentResult -----|                   |
  |                      |                      |                       |                   |
  |                      |  <-- RouterAgentResult|                       |                   |
  |                      |      task_type, model_used,                  |                   |
  |                      |      confidence, data, timing                |                   |
  |                      |                      |                       |                   |
  |  <-- 200 OK ---------|                      |                       |                   |
  |  InferResponse JSON  |                      |                       |                   |
```

### Flow 2: POST /benchmark (Manual Mode)

This bypasses the router. You pick the task and model.

```
Client                  API                 Specialized Agent      Ollama
  |                      |                       |                   |
  |  POST /benchmark     |                       |                   |
  |  {"task": "...",     |                       |                   |
  |   "model": "...",    |                       |                   |
  |   "input": "..."}   |                       |                   |
  |--------------------->|                       |                   |
  |                      |                       |                   |
  |                      |  validate task in     |                   |
  |                      |  AGENT_MAP            |                   |
  |                      |  validate model in    |                   |
  |                      |  MODELS               |                   |
  |                      |                       |                   |
  |                      |  Agent(model).run()   |                   |
  |                      |--------------------->|                   |
  |                      |                       |  POST /api/chat   |
  |                      |                       |  format: json     |
  |                      |                       |----------------->|
  |                      |                       |  <--- stream -----|
  |                      |                       |  validate schema  |
  |                      |  <-- AgentResult -----|                   |
  |                      |                       |                   |
  |  <-- 200 OK ---------|                       |                   |
  |  BenchmarkResponse   |                       |                   |
```

### Flow 3: Retry on Validation Failure

```
BaseAgent._call_ollama(prompt)
         |
         v
    raw JSON response
         |
         v
BaseAgent._validate(raw)
         |
         |--- success --> return AgentResult(success=True)
         |
         |--- ValidationError:
         |      "severity: value is not a valid enumeration member"
         |
         v
    retry_count = 1 (max 2)
         |
         v
    new prompt = original_input + "\n\nYour previous attempt failed:\n"
                 + "  - severity: value is not a valid enumeration member\n"
                 + "Try again."
         |
         v
BaseAgent._call_ollama(new_prompt)  <-- model sees its own error
         |
         v
    raw JSON response (hopefully fixed)
         |
         v
BaseAgent._validate(raw)
         |
         |--- success --> return AgentResult(success=True, retry_count=1)
         |
         |--- fail again --> retry_count = 2, try once more
         |
         |--- fail 3rd time --> return AgentResult(success=False,
         |                        error="Schema validation failed after 2 retries")
```

---

## Dry Runs (All 4 API Requests)

### Dry Run 1: GET /health

**Request:**
```
GET http://localhost:8000/health
```

**What happens:**
1. FastAPI receives GET request
2. `health()` function in `api/main.py` returns a dict

**Response (200 OK):**
```json
{
  "status": "ok"
}
```

No models loaded, no Ollama calls. Pure health check.

---

### Dry Run 2: GET /models

**Request:**
```
GET http://localhost:8000/models
```

**What happens:**
1. FastAPI receives GET request
2. `list_models()` in `api/main.py` reads `MODELS` and `ROUTER_MODEL_MAP` from config.py
3. Returns them as JSON

**Response (200 OK):**
```json
{
  "available_models": ["llama3.2", "phi4-mini", "qwen2.5:3b"],
  "router_model_map": {
    "log_classify": "qwen2.5:3b",
    "code_review": "llama3.2",
    "doc_extract": "qwen2.5:3b"
  }
}
```

No Ollama calls. Just config values.

---

### Dry Run 3: POST /infer (Router Mode)

**Request:**
```json
POST http://localhost:8000/infer
{
  "input": "[ERROR] Connection pool exhausted. Max retries exceeded for host db-primary-01"
}
```

**Step-by-step execution:**

1. `infer()` in `api/routes/infer.py` receives the request
2. Validates input is not empty -- passes
3. Creates `RouterAgent()` (which initializes BaseAgent with model="phi4-mini")
4. Calls `RouterAgent.run(user_input=...)`

**Step 1 inside RouterAgent -- classify:**

5. `super().run()` calls `BaseAgent.run()` which calls `_call_ollama()`:
   - HTTP POST to `http://localhost:11434/api/chat`
   - Body: `{"model": "phi4-mini", "messages": [system_prompt, user_input], "format": "json", "stream": true}`
6. Ollama streams back tokens. First token arrives at ~350ms (TTFT)
7. Full response received at ~800ms:
   ```json
   {"task_type": "log_classify", "confidence": 0.95, "reasoning": "Input is a server error log line with database connectivity failure indicators"}
   ```
8. `_validate()` parses JSON and validates against `RouterDecision` schema -- passes
9. Returns `AgentResult(success=True, data={...}, ttft_ms=350, tokens_per_sec=6.8, total_ms=800)`

**Step 2 inside RouterAgent -- dispatch:**

10. Extracts `task_type = "log_classify"` from the result
11. Looks up `ROUTER_MODEL_MAP["log_classify"]` = `"qwen2.5:3b"`
12. Creates `LogClassifierAgent(model="qwen2.5:3b")`
13. Calls `agent.run(user_input=...)`
14. BaseAgent calls `_call_ollama()`:
    - HTTP POST to Ollama with model="qwen2.5:3b", system_prompt for log classification
15. Ollama streams back response in ~600ms:
    ```json
    {"anomaly_type": "database", "severity": "high", "confidence": 0.92, "explanation": "Connection pool exhaustion indicates database connectivity issues with max retries exceeded"}
    ```
16. `_validate()` validates against `LogClassification` schema -- passes
17. Returns `AgentResult(success=True, data={...})`

**RouterAgent combines results:**

18. Creates `RouterAgentResult` with both routing metadata and agent output
19. API wraps it into `InferResponse`

**Response (200 OK):**
```json
{
  "task_type": "log_classify",
  "model_used": "qwen2.5:3b",
  "router_confidence": 0.95,
  "router_reasoning": "Input is a server error log line with database connectivity failure indicators",
  "success": true,
  "data": {
    "anomaly_type": "database",
    "severity": "high",
    "confidence": 0.92,
    "explanation": "Connection pool exhaustion indicates database connectivity issues with max retries exceeded"
  },
  "error": null,
  "retry_count": 0,
  "ttft_ms": 280.5,
  "tokens_per_sec": 9.46,
  "total_ms": 620.3,
  "routing_ms": 800.1
}
```

**Total time:** routing_ms (~800ms) + agent total_ms (~620ms) = ~1.4 seconds.

---

### Dry Run 4: POST /benchmark (Manual Mode)

**Request:**
```json
POST http://localhost:8000/benchmark
{
  "task": "code_review",
  "model": "llama3.2",
  "input": "def get_user(id): return db.query(f'SELECT * FROM users WHERE id={id}')"
}
```

**Step-by-step execution:**

1. `benchmark()` in `api/routes/benchmark.py` receives the request
2. Validates `task = "code_review"` is in `AGENT_MAP` -- passes
3. Validates `model = "llama3.2"` is in `MODELS` -- passes
4. Validates input is not empty -- passes
5. Looks up `AGENT_MAP["code_review"]` = `CodeReviewAgent`
6. Creates `CodeReviewAgent(model="llama3.2")`
7. Calls `agent.run(user_input=...)`

**Inside BaseAgent.run():**

8. Calls `_call_ollama()`:
   - HTTP POST to Ollama with model="llama3.2", code review system prompt
9. Ollama streams response in ~700ms:
   ```json
   {"issue_type": "security", "severity": "critical", "line_number": 1, "suggestion": "Use parameterized queries to prevent SQL injection instead of f-string concatenation", "confidence": 0.98}
   ```
10. `_validate()` validates against `CodeReviewResult` -- passes
11. Returns `AgentResult(success=True, data={...})`

**Response (200 OK):**
```json
{
  "task": "code_review",
  "model": "llama3.2",
  "success": true,
  "data": {
    "issue_type": "security",
    "severity": "critical",
    "line_number": 1,
    "suggestion": "Use parameterized queries to prevent SQL injection instead of f-string concatenation",
    "confidence": 0.98
  },
  "error": null,
  "retry_count": 0,
  "ttft_ms": 310.4,
  "tokens_per_sec": 8.84,
  "total_ms": 720.6
}
```

**Why use /benchmark?** To test a specific model on a specific task without the router overhead.
For example: "did the phi4-mini fix improve its code_review accuracy?" -- test directly, skip routing.

---

## Special Cases and Edge Cases

### Case 1: Empty Input

**Request:**
```json
POST /infer  {"input": ""}
POST /infer  {"input": "   "}
```

**What happens:**
- `infer.py` line 31: `if not request.input or not request.input.strip():`
- Raises `HTTPException(status_code=422, detail="input cannot be empty")`

**Response (422):**
```json
{"detail": "input cannot be empty"}
```

Same behavior on `/benchmark` (line 47 of benchmark.py).

---

### Case 2: Invalid Task or Model on /benchmark

**Request:**
```json
POST /benchmark  {"task": "sentiment", "model": "llama3.2", "input": "hello"}
```

**What happens:**
- `benchmark.py` line 37: `if request.task not in AGENT_MAP:`
- Raises 422 with valid options listed

**Response (422):**
```json
{"detail": "Unknown task: sentiment. Must be one of ['log_classify', 'code_review', 'doc_extract']"}
```

Same for invalid model:
```json
{"detail": "Unknown model: gpt-4. Must be one of ['llama3.2', 'phi4-mini', 'qwen2.5:3b']"}
```

---

### Case 3: Router Misclassifies the Input

**Request:**
```json
POST /infer
{
  "input": "SELECT * FROM users WHERE id = 1; DROP TABLE users; --"
}
```

**What could happen:**
- Router (phi4-mini) sees SQL and might classify as `log_classify` (it looks like a log line)
  OR `code_review` (it's SQL code)
- If classified as `log_classify`, the LogClassifierAgent runs on qwen2.5:3b
- LogClassifierAgent would still return a valid response, but it would classify the SQL
  as a "database anomaly" rather than identifying the SQL injection security issue

**This is the 6% failure case.** The router has 94% accuracy -- the other 6% go to the wrong
agent. The agent still produces a valid response, just not the most useful one.

---

### Case 4: Ollama Not Running

**Request:**
```json
POST /infer  {"input": "anything"}
```

**What happens:**
1. RouterAgent calls `_call_ollama()`
2. httpx tries to connect to `localhost:11434`
3. `httpx.ConnectError` caught in the except block (base_agent.py line 123)
4. Returns `(None, None, None, None)`
5. BaseAgent returns `AgentResult(success=False, error="Ollama call failed -- no response received")`
6. RouterAgent wraps this as `RouterAgentResult(success=False, error="Routing failed: ...")`
7. `infer.py` line 38: `if not result.success:` -- true
8. Line 39: `result.task_type is None` -- true, so status = 502

**Response (502):**
```json
{"detail": "Router failed to classify input: Routing failed: Ollama call failed -- no response received"}
```

---

### Case 5: Model Returns Invalid JSON

**Scenario:** Model generates `{"anomaly_type": "database", "severity": "extreme", ...}`
where `"extreme"` is not a valid Literal value.

**What happens:**
1. `_validate()` catches `ValidationError`:
   `severity: value is not a valid enumeration member; permitted: 'low', 'medium', 'high', 'critical'`
2. Error fed back to model in retry prompt
3. Model retries (up to 2 times)
4. If all retries fail:

**Response (if via /benchmark, agent returns error in data):**
```json
{
  "task": "log_classify",
  "model": "llama3.2",
  "success": false,
  "data": null,
  "error": "Schema validation failed after 2 retries. Last error: ...",
  "retry_count": 2,
  "ttft_ms": 310.4,
  "tokens_per_sec": 5.2,
  "total_ms": 3200.0
}
```

**If via /infer:** routing step would fail similarly, returning a 502.

---

### Case 6: Model Returns Non-JSON

**Scenario:** Model responds with `"I think this is a database error because..."` (no JSON).

**What happens:**
1. `_validate()` calls `json.loads(raw)` -- raises `JSONDecodeError`
2. Error message: `"Response was not valid JSON: Expecting value: line 1 column 1 (char 0)"`
3. This is fed back to model in retry prompt
4. Retry behavior same as Case 5

This rarely happens because Ollama's `"format": "json"` grammar constraint forces
JSON output structure. But some models can still produce malformed JSON under edge cases.

---

### Case 7: Cold Start Latency

**Scenario:** First call after server restart. Model not in Ollama RAM.

```
Normal (warm) call:  TTFT ~300ms,  total ~700ms
Cold start call:     TTFT ~3000ms, total ~5000ms
```

**What happens:**
1. First call to a model triggers Ollama to load it from disk into RAM
2. TTFT jumps 5-10x because of model loading overhead
3. Subsequent calls are warm (model stays in RAM until evicted)

The benchmark tracks this with `cold_start: true/false` so charts show the difference.

---

### Case 8: Concurrent Requests

**Scenario:** Two /infer requests arrive simultaneously.

**What happens:**
- FastAPI handles them concurrently via `run_in_threadpool()`
- Each creates its own `RouterAgent` instance
- Ollama processes requests sequentially (single-threaded inference)
- Second request waits while first is being processed
- No data races, no shared state between requests

---

### Case 9: Very Long Input

**Scenario:** User sends a 10,000 character log file.

**What happens:**
- No input length limit in the API (only empty check)
- Ollama has a context window limit (model-dependent, typically 2048-4096 tokens)
- If input exceeds context window, Ollama truncates silently
- Model may produce less accurate results on truncated input
- Response is still structurally valid (schema enforced)

---

### Case 10: Ambiguous Input

**Request:**
```json
POST /infer
{
  "input": "Connection timeout after 30s while executing SELECT * FROM orders"
}
```

**What happens:**
- This could be log_classify (connection timeout log) OR code_review (SQL query)
- Router's classification depends on which features it weights more heavily
- This is exactly the type of prompt in the "ambiguous" category of test prompts
- Router accuracy on ambiguous prompts is lower than on clear prompts

---

## Benchmark Results Summary

### Task Benchmark Results (9 combos, 250 runs each)

| Task | Model | Accuracy | tok/s | Notes |
|---|---|---|---|---|
| log_classify | llama3.2 | 94% (235/250) | 5.12 | Good but slower |
| log_classify | phi4-mini | 76% (190/250) | 6.08 | Poor accuracy |
| log_classify | qwen2.5:3b | 96% (240/250) | 9.46 | **Winner** |
| code_review | llama3.2 | 100% (250/250) | 8.84 | **Winner** (2x faster than qwen) |
| code_review | phi4-mini | 88% (220/250) | 6.85 | Acceptable |
| code_review | qwen2.5:3b | 100% (250/250) | 4.90 | Ties accuracy, but slower |
| doc_extract | llama3.2 | 100% (250/250) | 8.27 | Strong |
| doc_extract | phi4-mini | 100% (250/250) | 4.90 | Accurate but slowest |
| doc_extract | qwen2.5:3b | 100% (250/250) | 9.05 | **Winner** (fastest) |

### Router Eval Results (150 prompts each)

| Model | Accuracy | tok/s | Schema Validity |
|---|---|---|---|
| llama3.2 | 90.0% | 8.73 | 100.0% |
| phi4-mini | 94.0% | 6.83 | 99.3% |
| qwen2.5:3b | 92.7% | 9.15 | 100.0% |

### Final Config (data-driven)

```python
ROUTER_MODEL = "phi4-mini"           # 94% routing accuracy (best)
ROUTER_MODEL_MAP = {
    "log_classify": "qwen2.5:3b",   # 96% accuracy, 9.46 tok/s
    "code_review": "llama3.2",      # 100% accuracy, 8.84 tok/s
    "doc_extract": "qwen2.5:3b",    # 100% accuracy, 9.05 tok/s
}
```

### Analysis Charts

Generated by `analysis/compare.ipynb`, saved in `benchmark/results/`:

| Chart | What it Shows |
|---|---|
| speed_comparison.png | Token generation speed (tok/s) grouped by task and model |
| validity_rate.png | Schema validation success rate per model per task |
| ttft_cold_warm.png | Time-to-first-token: cold start vs warm, by model |
| category_breakdown.png | Pass rates broken down by prompt category (clear/ambiguous/edge/negative) |

---

## Configuration Reference

All configuration lives in `config.py`:

```python
# Ollama connection
OLLAMA_URL = "http://localhost:11434"

# Available models (must be pulled in Ollama first)
MODELS = ["llama3.2", "phi4-mini", "qwen2.5:3b"]

# Agent behavior
MAX_RETRIES = 2              # retry on validation failure (0 = no retries)
DEFAULT_TEMPERATURE = 0.0    # deterministic output (no randomness)

# Benchmark settings
BENCHMARK_RUNS = 5           # runs per prompt per model
TEST_PROMPTS_DIR = "benchmark/test_prompts"
RESULTS_DIR = "benchmark/results"

# Router config (updated after benchmark analysis)
ROUTER_MODEL = "phi4-mini"
ROUTER_MODEL_MAP = {
    "log_classify": "qwen2.5:3b",
    "code_review": "llama3.2",
    "doc_extract": "qwen2.5:3b",
}
```

---

## Command Reference

```powershell
# Start Ollama (must be running before API or benchmarks)
ollama serve

# Pull models (first time only)
ollama pull llama3.2
ollama pull phi4-mini
ollama pull qwen2.5:3b

# Run benchmark for a single combo
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m benchmark.harness --task log_classify --model llama3.2

# Run all 9 benchmark combos
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m benchmark.harness --task all --model all

# Run router eval (all models)
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m benchmark.router_eval

# Run router eval (single model)
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m benchmark.router_eval --model phi4-mini

# Start API server
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m uvicorn api.main:app --port 8000

# Open Swagger UI (interactive docs)
# http://localhost:8000/docs

# Run Jupyter notebook for analysis
$env:PYTHONUTF8=1; .venv\Scripts\python.exe -m jupyter notebook analysis/compare.ipynb
```
