"""Plan independent days concurrently, checkpoint responses, then validate in order."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
from queue import Empty, SimpleQueue
from typing import Callable

from .config import Config
from .models import (
    DayPayload, DayResult, ItineraryPayload, PlannerResult, PlanningOutline,
    RoleGeneration, SavedPlan, TokenUsage, TripRequest,
)
from .openai_service import AIServiceError, OpenAIService, json_data
from .validation import _matches, payload_from_plan, validate_day_outline, validate_day_prefix, validate_independent_day


def plan_context(plan: SavedPlan) -> dict:
    """Omit storage envelopes and computed totals from model input."""
    return {"request": plan.request.model_dump(mode="json"),
            "itinerary": payload_from_plan(plan).model_dump(mode="json")}


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
        *,
        checkpoint: dict | None = None,
        save_checkpoint: Callable[[dict], None] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> PlannerResult:
        self.last_metadata = None
        rules = files("trip_planner").joinpath("prompts/planning_rules.txt").read_text(encoding="utf-8")
        outline_prompt = files("trip_planner").joinpath("prompts/outline.txt").read_text(encoding="utf-8")
        day_prompt = files("trip_planner").joinpath("prompts/day.txt").read_text(encoding="utf-8")
        context = {
            "validated_request": request.model_dump(mode="json"),
            "current_plan": plan_context(current) if current else None,
            "change_instructions": instructions,
            "validation_feedback": feedback,
        }
        # Settings that only affect transport/output limits can change on Retry.
        identity = sha256(json_data({"context": context, "model": self.config.planner_model,
                                    "checkpoint_version": 2,
                                    "prompts": [rules, outline_prompt, day_prompt]}).encode()).hexdigest()
        state = deepcopy(checkpoint) if checkpoint and checkpoint.get("identity") == identity else {
            "identity": identity, "days": [], "ready_days": {}, "metadata": [],
        }
        notify = progress or (lambda message: None)

        def save():
            if save_checkpoint:
                save_checkpoint(deepcopy(state))

        def call(prompt, data, response_model):
            result = self.service.parse(role="planner", prompt=prompt, data=data,
                                        response_model=response_model, progress=progress)
            metadata = self.service.last_metadata
            if metadata:
                state["metadata"].append(metadata.model_dump(mode="json"))
                save()
            return result

        save()
        if "outline" not in state:
            notify("Choosing the route and daily outline…")
            outline_feedback = feedback
            for attempt in range(2):
                outline = call(outline_prompt + "\n\n" + rules,
                               {**context, "validation_feedback": outline_feedback}, PlanningOutline)
                if outline.clarification_question:
                    return PlannerResult(itinerary=None, clarification_question=outline.clarification_question,
                                         assistant_message=outline.assistant_message)
                try:
                    self._validate_outline(outline, request)
                    break
                except ValueError as exc:
                    if attempt:
                        raise AIServiceError(f"The route outline needs correction: {exc}") from exc
                    outline_feedback = str(exc)
            state["outline"] = outline.model_dump(mode="json")
            save()
        outline = PlanningOutline.model_validate(state["outline"])
        self._validate_outline(outline, request)
        days = [DayPayload.model_validate(value) for value in state["days"]]
        if days:
            validate_day_prefix(days, request)
            notify(f"Resuming with {len(days)} of {request.duration_days} days already saved.")
        pending = {key: DayPayload.model_validate(value) for key, value in state.get("ready_days", {}).items()}
        reused = set(state.get("reused_days", []))
        can_reuse = current is not None and current.request == request
        entries = outline.days[len(days):]
        for entry in entries:
            key = str(entry.day_number)
            if key not in pending and can_reuse and entry.reuse_existing:
                pending[key] = DayPayload.model_validate(current.days[entry.day_number - 1].model_dump(exclude={"estimated_total_cost"}))
                reused.add(key)
        state["ready_days"] = {key: day.model_dump(mode="json") for key, day in pending.items()}
        state["reused_days"] = sorted(reused)
        save()

        def day_data(entry, candidate=None, day_feedback=""):
            number = entry.day_number
            return {
                "validated_request": context["validated_request"],
                "outline": outline.model_dump(mode="json"),
                "day_to_generate": entry.model_dump(mode="json"),
                "previous_day_outline": outline.days[number - 2].model_dump(mode="json") if number > 1 else None,
                "next_day_outline": outline.days[number].model_dump(mode="json") if number < len(outline.days) else None,
                "previous_day": days[number - 2].model_dump(mode="json") if 1 < number <= len(days) + 1 else None,
                "next_day": pending[str(number + 1)].model_dump(mode="json") if str(number + 1) in pending else None,
                "existing_day": (current.days[number - 1].model_dump(mode="json", exclude={"estimated_total_cost"})
                                 if current and number <= len(current.days) else None),
                "change_instructions": instructions,
                "candidate_to_repair": candidate,
                "validation_feedback": day_feedback,
            }

        missing = [entry for entry in entries if str(entry.day_number) not in pending]
        try:
            clarification = self._fetch_days(missing, day_prompt + "\n\n" + rules, day_data, request, state, save, notify)
        except Exception:
            # Validate any contiguous successes before surfacing a failed call.
            # Later completed responses remain cached even across a gap.
            for entry in entries:
                key = str(entry.day_number)
                if key not in state["ready_days"]:
                    break
                candidate = DayPayload.model_validate(state["ready_days"][key])
                try:
                    validate_day_outline(candidate, entry)
                    validate_day_prefix(days + [candidate], request)
                except ValueError as exc:
                    state["invalid_day"] = {"feedback": str(exc), "candidate": candidate.model_dump(mode="json")}
                    save()
                    break
                days.append(candidate)
                state["days"] = [day.model_dump(mode="json") for day in days]
                state["ready_days"].pop(key)
                save()
            raise
        if clarification:
            return PlannerResult(itinerary=None, clarification_question=clarification, assistant_message="")
        pending = {key: DayPayload.model_validate(value) for key, value in state["ready_days"].items()}
        for entry in entries:
            number, key = entry.day_number, str(entry.day_number)
            candidate = pending[key]
            try:
                validate_day_outline(candidate, entry)
                validate_day_prefix(days + [candidate], request)
            except ValueError as exc:
                # All network results are checkpointed already. Repair only the
                # first invalid day with its fixed neighbors, keeping later results.
                day_feedback = str(exc)
                attempts = 2 if key in reused else 1
                for attempt in range(attempts):
                    state["invalid_day"] = {"feedback": day_feedback, "candidate": candidate.model_dump(mode="json")}
                    save()
                    notify(f"Correcting Day {number}: {day_feedback}")
                    result = call(day_prompt + "\n\n" + rules,
                                  day_data(entry, candidate.model_dump(mode="json"), day_feedback), DayResult)
                    if result.clarification_question or result.day is None:
                        return PlannerResult(itinerary=None,
                                             clarification_question=result.clarification_question or "Which trip constraint can be adjusted to make this day feasible?",
                                             assistant_message="")
                    candidate = result.day
                    state["ready_days"][key] = candidate.model_dump(mode="json")
                    reused.discard(key)
                    state["reused_days"] = sorted(reused)
                    try:
                        validate_day_outline(candidate, entry)
                        validate_day_prefix(days + [candidate], request)
                        break
                    except ValueError as repair_error:
                        day_feedback = str(repair_error)
                        state["invalid_day"] = {"feedback": day_feedback, "candidate": candidate.model_dump(mode="json")}
                        save()
                        if attempt == attempts - 1:
                            raise AIServiceError(f"Day {number} still needs correction: {day_feedback} Completed responses are saved; Retry repairs this day.") from repair_error
            days.append(candidate)
            state["days"] = [day.model_dump(mode="json") for day in days]
            state["ready_days"].pop(key)
            state.pop("invalid_day", None)
            reused.discard(key)
            state["reused_days"] = sorted(reused)
            save()
            notify(f"Saved Day {number} of {request.duration_days}.")
        records = [RoleGeneration.model_validate(value) for value in state["metadata"]]
        if records:
            totals = {key: sum(getattr(record.usage, key) or 0 for record in records if record.usage)
                      for key in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")}
            self.last_metadata = records[-1].model_copy(update={"usage": TokenUsage(**totals)})
        return PlannerResult(itinerary=ItineraryPayload(summary=outline.summary, days=days,
                                                        assumptions=outline.assumptions, warnings=outline.warnings),
                             clarification_question=None, assistant_message=outline.assistant_message)

    def _fetch_days(self, entries, prompt, day_data, request, state, save, notify):
        """Bound in-flight calls; only the caller writes state or talks to the UI."""
        if not entries:
            return None
        progress_events = SimpleQueue()

        def fetch(entry, data):
            for attempt in range(2):
                result = self.service.parse(
                    role="planner", prompt=prompt, data=data, response_model=DayResult,
                    progress=lambda message: progress_events.put(("progress", f"Day {entry.day_number}: {message}")),
                )
                # Even an invalid response is recoverable: persist it before its
                # repair finishes, and keep metadata separate for every call.
                progress_events.put(("response", entry, result, self.service.last_metadata))
                if result.clarification_question or result.day is None:
                    return result
                try:
                    validate_independent_day(result.day, request, entry)
                    return result
                except ValueError as exc:
                    if attempt:
                        raise AIServiceError(f"Day {entry.day_number} still needs correction: {exc} Completed responses are saved; Retry repairs this day.") from exc
                    data = {**data, "candidate_to_repair": result.day.model_dump(mode="json"),
                            "validation_feedback": str(exc)}
                    progress_events.put(("progress", f"Correcting Day {entry.day_number}: {exc}"))

        iterator = iter(entries)
        failure = None
        clarification = None
        workers = min(self.config.planner_workers, len(entries))
        notify(f"Generating up to {workers} days at once…")

        def drain_events():
            while True:
                try:
                    event = progress_events.get_nowait()
                except Empty:
                    break
                if event[0] == "progress":
                    notify(event[1])
                    continue
                _, entry, result, metadata = event
                if metadata:
                    state["metadata"].append(metadata.model_dump(mode="json"))
                if result.day is not None and not result.clarification_question:
                    state["ready_days"][str(entry.day_number)] = result.day.model_dump(mode="json")
                save()

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trip-day") as executor:
            running = {}

            def submit_next():
                entry = next(iterator, None)
                if entry is not None:
                    notify(f"Planning Day {entry.day_number}…")
                    running[executor.submit(fetch, entry, day_data(entry))] = entry

            for _ in range(workers):
                submit_next()
            while running:
                finished, _ = wait(running, timeout=0.1, return_when=FIRST_COMPLETED)
                drain_events()
                for future in finished:
                    entry = running.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        failure = failure or exc
                        notify(f"Day {entry.day_number} could not complete; saving other in-flight responses…")
                        continue
                    if result.clarification_question or result.day is None:
                        clarification = clarification or result.clarification_question or "Which trip constraint can be adjusted to make this day feasible?"
                    else:
                        notify(f"Received Day {entry.day_number}; checking schedules after generation.")
                # On failure, do not start more calls. Drain existing calls so
                # successful out-of-order responses survive a retry or restart.
                if not failure and not clarification:
                    for _ in finished:
                        submit_next()
            drain_events()
        if failure:
            raise failure
        return clarification

    @staticmethod
    def _validate_outline(outline, request):
        if [day.day_number for day in outline.days] != list(range(1, request.duration_days + 1)):
            raise ValueError(f"Include exactly {request.duration_days} consecutively numbered days.")
        if any(not day.destinations or not day.title.strip() for day in outline.days):
            raise ValueError("Each day needs destinations and a title.")
        for index, day in enumerate(outline.days):
            if not all(value.strip() for value in (day.start_location, day.end_location, day.overnight_base)):
                raise ValueError("Every day needs start_location, end_location, and overnight_base.")
            if index and day.start_location != outline.days[index - 1].end_location:
                raise ValueError("Each day's start_location must equal the preceding day's end_location.")
            if day.incoming_transfer and (day.incoming_transfer.duration_minutes <= 0
                                         or not all(value.strip() for value in (day.incoming_transfer.origin, day.incoming_transfer.destination,
                                                                               day.incoming_transfer.transport_mode))):
                raise ValueError("An incoming transfer needs real endpoints, a transport mode, and positive travel time.")
            if day.start_location != day.end_location and day.incoming_transfer is None:
                raise ValueError("A change of overnight city/base needs an incoming_transfer on that day.")
            if day.incoming_transfer and not (_matches(day.start_location, day.incoming_transfer.origin)
                                              and _matches(day.end_location, day.incoming_transfer.destination)):
                raise ValueError("An incoming transfer must connect that day's start_location and end_location.")
        if not request.destination_delegated:
            visits = []
            for day in outline.days:
                for destination in day.destinations:
                    if destination in request.destinations and destination not in visits:
                        visits.append(destination)
            if visits != request.destinations:
                raise ValueError("Include every exact requested destination label in the requested order.")
