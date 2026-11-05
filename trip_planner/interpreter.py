"""Interpret labeled answers and chat; never generate an itinerary here."""

from datetime import datetime
from importlib.resources import files
from zoneinfo import ZoneInfo

from .config import Config
from .models import InterpreterResult, RequestDraft, SavedPlan
from .openai_service import OpenAIService
from .planner import plan_context


class Interpreter:
    def __init__(self, config: Config, service: OpenAIService | None = None):
        self.config = config
        self.service = service if service is not None else OpenAIService(config)
        self.last_metadata = None

    def interpret(
        self,
        *,
        answers: dict,
        draft: RequestDraft,
        message: str = "",
        history: list | None = None,
        plan: SavedPlan | None = None,
        pending: dict | None = None,
        progress=None,
    ) -> InterpreterResult:
        self.last_metadata = None
        self.config.validate_live("interpreter")
        prompt = files("trip_planner").joinpath("prompts/interpreter.txt").read_text(encoding="utf-8")
        data = {
            "local_date": datetime.now(ZoneInfo(self.config.timezone)).date().isoformat(),
            "timezone": self.config.timezone,
            "labeled_answers": answers,
            "request_draft": draft.model_dump(mode="json"),
            "message": message,
            "recent_conversation": (history or [])[-12:],
            "active_plan": {**plan_context(plan), "budget_summary": plan.budget_summary.model_dump(mode="json")} if plan else None,
            # Checkpoints are local recovery state, not interpretation context.
            "pending_edit": {key: value for key, value in (pending or {}).items()
                             if key in {"instructions", "assumptions", "message", "request"}} or None,
        }
        result = self.service.parse(role="interpreter", prompt=prompt, data=data,
                                    response_model=InterpreterResult, progress=progress)
        self.last_metadata = self.service.last_metadata
        return result
