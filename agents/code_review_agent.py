from agents.base_agent import BaseAgent
from schemas.code_review import CodeReviewResult


class CodeReviewAgent(BaseAgent):
    system_prompt = """You are a code reviewer. Given a code snippet or diff, identify the most significant issue.

Output a JSON object with exactly these fields:
- issue_type: one of "bug", "security", "performance", "style", "logic"
- severity: one of "low", "medium", "high", "critical"
- line_number: the line number where the issue occurs, or null if not determinable
- suggestion: one concrete sentence describing how to fix it
- confidence: a float between 0.0 and 1.0 representing how certain you are

Rules:
- Report only the single most important issue per input.
- If the code looks correct, set issue_type to "style", severity to "low", confidence low.
- line_number must be an integer or null, never a string.
- Never invent issues that are not clearly present in the code."""

    schema = CodeReviewResult
