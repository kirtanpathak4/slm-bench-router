from fastapi import FastAPI

from api.routes import benchmark, infer
from config import MODELS, ROUTER_MODEL_MAP

app = FastAPI(
    title="slm-bench-router",
    description="Benchmark platform for local SLMs via Ollama. Two modes: router (auto-picks model) and benchmark (manual model+task).",
    version="0.1.0",
)

app.include_router(infer.router, tags=["router mode"])
app.include_router(benchmark.router, tags=["benchmark mode"])


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/models", tags=["system"])
def list_models():
    return {
        "available_models": MODELS,
        "router_model_map": ROUTER_MODEL_MAP,
    }
