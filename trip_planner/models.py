"""Typed AI contracts and the authoritative saved-plan format."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Pace = Literal["relaxed", "balanced", "packed"]
CostCategory = Literal["accommodation", "food", "transport", "activities", "other"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RequestDraft(Model):
    trip_name: str | None = None
    destinations: list[str] | None = None
    duration_days: int | None = None
    budget: float | None = None
    currency: str | None = None
    preferences: str | None = None
    start_date: date | None = None
    travelers: int | None = None
    pace: Pace | None = None
    budget_per_person: bool | None = None
    travelers_explicit: bool | None = None
    destination_delegated: bool | None = None


class TripRequest(Model):
    trip_name: str
    destinations: list[str]
    duration_days: int
    budget: float | None = None
    currency: str = "USD"
    preferences: str = ""
    start_date: date | None = None
    travelers: int = 1
    pace: Pace = "balanced"
    destination_delegated: bool = False


class InterpreterResult(Model):
    intent: Literal["create", "edit", "question", "list", "resume", "show", "open", "undo", "cancel", "help", "exit"]
    request_draft: RequestDraft
    request_updates: RequestDraft
    change_instructions: str
    trip_reference: str | None
    missing_required_fields: list[str]
    clarification_question: str | None
    assumptions: list[str]
    assistant_message: str
    clear_fields: list[Literal["budget", "start_date"]] = Field(default_factory=list)


class Cost(Model):
    category: CostCategory
    amount: float | None
    currency: str
    label: str | None = None


class Travel(Model):
    origin: str
    destination: str
    transport_mode: str
    duration_minutes: int
    route_notes: str


class ScheduleItem(Model):
    # New items use null; only IDs belonging to surviving items are retained.
    id: str | None = None
    kind: Literal["activity", "meal", "travel", "rest", "free_time"]
    title: str
    description: str
    start_time: str
    end_time: str
    start_timezone: str
    end_timezone: str
    start_day_offset: int
    end_day_offset: int
    duration_minutes: int
    place_name: str | None
    location: str | None
    travel: Travel | None
    cost: Cost
    notes: list[str]


class DayPayload(Model):
    day_number: int
    date: date | None
    title: str
    summary: str
    destinations: list[str]
    schedule: list[ScheduleItem]
    additional_costs: list[Cost]
    notes: list[str]


class Day(DayPayload):
    estimated_total_cost: float


class ItineraryPayload(Model):
    summary: str
    days: list[DayPayload]
    assumptions: list[str]
    warnings: list[str]


class PlannerResult(Model):
    itinerary: ItineraryPayload | None
    clarification_question: str | None
    assistant_message: str


class TokenUsage(Model):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class RoleGeneration(Model):
    role: Literal["interpreter", "planner"]
    provider: str
    model: str | None
    generated_at: str
    usage: TokenUsage | None = None


class GenerationMetadata(Model):
    provider: str = "unknown"
    model: str | None = None
    generated_at: str = ""
    usage: TokenUsage | None = None
    demo: bool = False
    roles: list[RoleGeneration] = Field(default_factory=list)


class BudgetSummary(Model):
    scope: str
    category_totals: dict[str, float]
    estimated_total: float
    budget_limit: float | None
    remaining: float | None
    currency: str
    status: Literal["no_limit", "within_budget", "over_budget", "uncertain"]
    partial: bool


class SavedPlan(Model):
    schema_version: str = "1.0"
    trip_id: str
    revision: int
    created_at: str
    updated_at: str
    request: TripRequest
    summary: str
    days: list[Day]
    budget_summary: BudgetSummary
    assumptions: list[str]
    warnings: list[str]
    generation: GenerationMetadata
