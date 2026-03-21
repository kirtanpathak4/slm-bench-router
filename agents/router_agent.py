from pydantic import BaseModel

from agents.base_agent import AgentResult, BaseAgent
from agents.code_review_agent import CodeReviewAgent
from agents.doc_extractor_agent import DocExtractorAgent
from agents.log_classifier_agent import LogClassifierAgent
from config import ROUTER_MODEL, ROUTER_MODEL_MAP
from schemas.router import RouterDecision


class RouterAgentResult(BaseModel):
    success: bool
    task_type: str | None = None
    model_used: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    routing_ms: float | None = None    # time spent on the classification call
    result: AgentResult | None = None  # output from the specialized agent
    error: str | None = None


class RouterAgent(BaseAgent):
    # system prompt must match what was used in benchmark/router_eval.py
    # — changing this wording will invalidate the 94% accuracy measurement
    system_prompt = (
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
    schema = RouterDecision

    _task_agents = {
        "log_classify": LogClassifierAgent,
        "code_review":  CodeReviewAgent,
        "doc_extract":  DocExtractorAgent,
    }

    def __init__(self):
        super().__init__(model=ROUTER_MODEL)

    def run(self, user_input: str, cold_start: bool = False) -> RouterAgentResult:
        # Step 1: classify the request using ROUTER_MODEL (phi4-mini)
        routing = super().run(user_input=user_input, cold_start=cold_start)

        if not routing.success:
            return RouterAgentResult(
                success=False,
                error=f"Routing failed: {routing.error}",
                routing_ms=routing.total_ms,
            )

        if not routing.data:
            return RouterAgentResult(
                success=False,
                error="Routing returned no data",
                routing_ms=routing.total_ms,
            )

        task_type  = routing.data.get("task_type")
        confidence = routing.data.get("confidence")
        reasoning  = routing.data.get("reasoning")

        if task_type not in ROUTER_MODEL_MAP:
            return RouterAgentResult(
                success=False,
                error=f"Unknown task_type from router: {task_type}",
                routing_ms=routing.total_ms,
            )

        model = ROUTER_MODEL_MAP[task_type]

        # Step 2: dispatch to specialized agent with the benchmark-optimal model
        agent  = self._task_agents[task_type](model=model)
        result = agent.run(user_input=user_input, cold_start=False)

        return RouterAgentResult(
            success=result.success,
            task_type=task_type,
            model_used=model,
            confidence=confidence,
            reasoning=reasoning,
            routing_ms=routing.total_ms,
            result=result,
            error=result.error,
        )
