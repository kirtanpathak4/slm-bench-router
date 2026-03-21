from agents.base_agent import BaseAgent
from schemas.log_classification import LogClassification


class LogClassifierAgent(BaseAgent):
    system_prompt = """You are a log anomaly classifier. Given a raw log line, classify it.

Output a JSON object with exactly these fields:
- anomaly_type: one of "database", "network", "memory", "auth", "storage", "application"
- severity: one of "low", "medium", "high", "critical"
- confidence: a float between 0.0 and 1.0 representing how certain you are
- explanation: one sentence explaining why you classified it this way

Rules:
- If the log line is not an anomaly or error, still classify it but use low severity and low confidence.
- If the input is empty or unreadable, set confidence to 0.0 and explain why.
- Never guess a severity higher than the evidence supports."""

    schema = LogClassification
