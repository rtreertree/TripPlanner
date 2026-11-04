"""A planning-only role receiving complete, locally validated trip constraints."""

from importlib.resources import files

from .config import Config
from .models import PlannerResult, SavedPlan, TripRequest
from .openai_service import OpenAIService


class Planner:
    def __init__(self, config: Config, service: OpenAIService | None = None):
        self.config = config
        self.service = service if service is not None else OpenAIService(config)
        self.last_metadata = None

    def plan(
        self,
        request: TripRequest,
        current: SavedPlan | None = None,
        instructions: str = "",
        feedback: str = "",
    ) -> PlannerResult:
        self.last_metadata = None
        filename = "revision.txt" if current else "planning.txt"
        prompt = files("trip_planner").joinpath("prompts", filename).read_text(encoding="utf-8")
        # The shared rules remain authoritative for both initial plans and revisions.
        rules = files("trip_planner").joinpath("prompts/planning_rules.txt").read_text(encoding="utf-8")
        data = {
            "validated_request": request.model_dump(mode="json"),
            "current_plan": current.model_dump(mode="json") if current else None,
            "change_instructions": instructions,
            "validation_feedback": feedback,
        }
        result = self.service.parse(
            role="planner", prompt=prompt + "\n\n" + rules, data=data, response_model=PlannerResult,
        )
        self.last_metadata = self.service.last_metadata
        return result
