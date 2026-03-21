OLLAMA_URL = "http://localhost:11434"

# models available
MODELS = ["llama3.2", "phi4-mini", "qwen2.5:3b"]

# agent defaults
MAX_RETRIES = 2
DEFAULT_TEMPERATURE = 0.0

# benchmark settings
BENCHMARK_RUNS = 5
TEST_PROMPTS_DIR = "benchmark/test_prompts"
RESULTS_DIR = "benchmark/results"

# router config — updated after benchmark analysis
# maps task_type → best model found in benchmarks
ROUTER_MODEL = "phi4-mini"  # model used by RouterAgent itself — 94% routing accuracy (router_eval)
ROUTER_MODEL_MAP = {
    "log_classify": "qwen2.5:3b",  # 96% accuracy, 9.46 tok/s
    "code_review": "llama3.2",     # 100% accuracy, 8.84 tok/s (ties qwen, 2x faster cold)
    "doc_extract": "qwen2.5:3b",   # 100% accuracy, 9.05 tok/s
}
