"""The sequential describe → view → refine flow, with explicit recovery points."""

from pathlib import Path
import webbrowser

from .models import GenerationMetadata, RequestDraft, RoleGeneration, SavedPlan
from .renderer import render_plan
from .storage import Session, Store
from .validation import build_plan, normalize_request

PROMPTS = [
    ("trip_name", "Trip name (optional): ", True),
    ("duration_days", "Days: ", False),
    ("destinations", "Destinations: ", False),
    ("budget", "Budget (optional): ", True),
    ("preferences", "Preferences / special requests (optional): ", True),
]
HELP = ('Try “Make Day 2 more relaxed”, “Why this neighborhood?”, “Show my plan”, '
        '“List my saved trips”, “Continue my Japan trip”, or “Undo my last change”. '
        'Type Exit to leave. Changes are made here in the terminal.')
LOCAL_ACTIONS = {
    "help": "help", "what can you do?": "help", "what can you do": "help",
    "exit": "exit", "quit": "exit", "bye": "exit",
    "show": "show", "show my plan": "show", "show the plan": "show",
    "open": "open", "open the infographic": "open", "open my plan": "open",
    "list": "list", "list my saved trips": "list", "list trips": "list",
    "new": "create", "start a new trip": "create",
    "undo": "undo", "undo my last change": "undo",
    "cancel": "cancel", "retry": "retry",
}


class LeaveSession(Exception):
    pass


class Application:
    def __init__(self, config, store: Store, interpreter, planner, *, no_open=False,
                 read=input, write=print, renderer=render_plan, browser=webbrowser.open):
        self.config, self.store = config, store
        self.interpreter, self.planner = interpreter, planner
        self.no_open, self.read, self.write = no_open, read, write
        self.renderer, self.browser = renderer, browser
        self.session: Session | None = None
        self.plan: SavedPlan | None = None

    def say(self, message):
        self.write(f"Assistant: {message}")

    def persist(self):
        while True:
            try:
                self.store.save_session(self.session)
                return
            except OSError:
                self.say("The latest progress is not yet saved. Check folder permissions, then type Retry or Exit.")
                if self.read("You: ").strip().casefold() != "retry":
                    raise LeaveSession("The latest progress could not be saved; only previously saved work can be resumed.")

    def add_history(self, role, message):
        self.session.history.append({"role": role, "content": message})

    def select_trip(self, reference=None):
        entries = self.store.list_trips()
        for warning in self.store.warnings:
            self.say(warning)
        if not entries and reference is None:
            return self.new_trip()
        self.write("1. Start a new trip")
        for index, entry in enumerate(entries, 2):
            self.write(f"{index}. {entry['status']} · {entry['name']} · {entry['destinations'] or 'Destinations pending'} · {entry['updated_at']}")
        while True:
            choice = reference or self.read("Choose a number or trip name (Exit to leave): ").strip()
            reference = None
            if choice.casefold() in {"exit", "quit"}:
                raise LeaveSession()
            if choice.casefold() in {"1", "new", "start a new trip"}:
                return self.new_trip()
            matches = []
            if choice.isdigit() and 2 <= int(choice) <= len(entries) + 1:
                matches = [entries[int(choice) - 2]]
            elif choice:
                matches = [entry for entry in entries if choice.casefold() in entry["name"].casefold()]
            if len(matches) == 1:
                self.session = self.store.load_session(matches[0]["trip_id"])
                folder = self.store.directory(self.session.trip_id)
                self.plan = self.store.load_plan(self.session.trip_id) if (folder / "plan.json").exists() else None
                if self.plan and self.session.stage == "chat" and self.session.draft.duration_days is None:
                    self.session.draft = RequestDraft.model_validate(self.plan.request.model_dump())
                # A committed plan may be newer than an interrupted session write.
                if self.plan and self.session.pending.get("base_revision", self.plan.revision) < self.plan.revision:
                    self.session.pending = {}
                    self.session.stage = "chat"
                if self.plan:
                    self.summary()
                    self.show_page(open_browser=not self.no_open)
                if self.session.stage in {"interpret", "generate"}:
                    self.recover("An operation was interrupted. It has not been repeated. Type Retry or Exit" + (", or Cancel to keep your saved plan." if self.plan else "."))
                return
            self.say("Several trips match. Choose its number from the list." if len(matches) > 1 else "No matching trip. Choose a number or part of a trip name.")

    def new_trip(self):
        self.config.validate_live()
        self.session, self.plan = Session(), None
        self.persist()
        self.say("Tell me about your trip. Press Enter or type ‘skip’ for optional questions. Type ‘back’ to change the previous answer, or ‘help’ for examples. You can change the plan afterward.")

    def collect(self):
        while self.session.prompt_index < len(PROMPTS):
            index = self.session.prompt_index
            field, label, optional = PROMPTS[index]
            if field in self.session.answers:
                self.write(f"Current answer: {self.session.answers[field] or '(skipped)'}")
            answer = self.read(label).strip()
            command = answer.casefold()
            if command in {"exit", "quit"}:
                raise LeaveSession()
            if command == "help":
                self.say("For example: a week; Tokyo then Kyoto; 150,000 yen for the group; quiet places and local food.")
                continue
            if command == "back":
                if index == 0:
                    self.say("There is no earlier answer. Enter a trip name or skip.")
                else:
                    self.session.prompt_index = index - 1
                    self.persist()
                continue
            if not optional and command in {"", "skip"}:
                self.say("How many days? For example, ‘five days’." if field == "duration_days" else "Where would you like to go? For example, ‘Tokyo then Kyoto’.")
                continue
            self.session.answers[field] = "" if command == "skip" else answer
            self.session.skipped = [key for key, value in self.session.answers.items() if not value]
            self.session.prompt_index = next((i for i, (key, _, _) in enumerate(PROMPTS) if key not in self.session.answers), len(PROMPTS))
            self.persist()
        self.session.stage = "interpret"
        self.persist()

    def summary(self):
        plan = self.plan
        budget = plan.budget_summary
        estimate = f"{budget.estimated_total:,.2f} {budget.currency}"
        if budget.partial:
            estimate += " (partial; some costs unknown)"
        self.say(f"{plan.request.trip_name}: {' → '.join(plan.request.destinations)} · {plan.request.duration_days} days · {plan.request.travelers} traveler(s). Estimated group total: {estimate}. Revision {plan.revision} is saved.")
        for warning in plan.warnings:
            self.say(warning)

    def show_page(self, open_browser=False):
        path = self.store.directory(self.plan.trip_id) / "itinerary.html"
        try:
            # Always use the authoritative JSON, including on resume/render retry.
            self.renderer(self.store.load_plan(self.plan.trip_id), path)
        except (OSError, ValueError) as exc:
            self.say("Your plan is saved, but the page could not be created. Type Retry to render it again, or continue chatting.")
            self.session.pending["render_failed"] = True
            self.persist()
            return
        self.session.pending.pop("render_failed", None)
        self.write(f"Infographic: {path.resolve()}")
        if open_browser:
            try:
                opened = self.browser(path.resolve().as_uri())
            except (OSError, webbrowser.Error):
                opened = False
            if not opened:
                self.say("The browser could not open automatically. Open the saved HTML path above.")

    def recover(self, message):
        self.say(message)
        while True:
            answer = self.read("You: ").strip()
            action = LOCAL_ACTIONS.get(answer.casefold())
            if action == "retry":
                return
            if action == "exit":
                raise LeaveSession()
            if action == "cancel" and self.plan:
                self.cancel()
                return
            if action in {"help", "show", "open", "list"}:
                self.dispatch(action)
                if action == "list":
                    return
            else:
                self.say("Type Retry or Exit" + (", or Cancel to keep the saved plan." if self.plan else "."))

    def interpret(self):
        self.say("Understanding your trip…" if not self.plan else "Understanding your message…")
        result = self.interpreter.interpret(answers=self.session.answers, draft=self.session.draft,
                    message=self.session.pending.get("message", ""), history=self.session.history[-12:],
                    plan=self.plan, pending=self.session.pending or None, progress=self.say)
        metadata = getattr(self.interpreter, "last_metadata", None)
        if metadata:
            self.session.interpretation_metadata.append(metadata.model_dump(mode="json"))
            self.session.interpretation_metadata = self.session.interpretation_metadata[-20:]
        if self.plan and result.intent == "create":
            self.session.stage = "clarify" if self.session.clarification else "chat"
            self.dispatch("create")
            return
        if result.intent in {"question", "help", "show", "open", "list", "resume", "undo", "cancel", "exit"}:
            if result.intent == "question":
                self.say(result.assistant_message)
                self.add_history("assistant", result.assistant_message)
                self.session.stage = "clarify" if self.session.clarification else "chat"
                self.persist()
            else:
                self.session.stage = "clarify" if self.session.clarification else "chat"
                self.persist()
                self.dispatch(result.intent, result.trip_reference)
            return
        updates = result.request_updates if self.plan else result.request_draft
        data = self.session.draft.model_dump()
        data.update(updates.model_dump(exclude_none=True))
        for field in getattr(result, "clear_fields", []):
            if field in {"budget", "start_date"}:
                data[field] = None
        self.session.draft = RequestDraft.model_validate(data)
        if result.change_instructions:
            old = self.session.pending.get("instructions", "")
            self.session.pending["instructions"] = "\n".join(filter(None, [old, result.change_instructions]))
        self.session.pending.pop("message", None)
        self.session.pending["assumptions"] = result.assumptions
        try:
            if result.clarification_question:
                raise ValueError(result.clarification_question)
            if result.missing_required_fields:
                raise ValueError("Please clarify " + ", ".join(result.missing_required_fields) + ".")
            request = normalize_request(self.session.draft)
        except ValueError as exc:
            self.session.clarification = str(exc)
            self.session.stage = "clarify"
            self.persist()
            return
        if self.session.draft.currency is None:
            currencies = {code.strip().upper() for code in self.session.draft.destination_currencies or []}
            reason = "the destinations use different currencies" if len(currencies) > 1 else "the destinations share this local currency"
            self.session.pending["assumptions"].append(f"Estimates are reported in {request.currency} because {reason}.")
        # Once converted, budgets remain group totals when traveler count changes.
        self.session.draft = RequestDraft.model_validate({**request.model_dump(), "budget_per_person": False,
                                                          "travelers_explicit": self.session.draft.travelers_explicit})
        self.session.pending["request"] = request.model_dump(mode="json")
        self.session.pending.pop("generation", None)
        self.session.pending["base_revision"] = self.plan.revision if self.plan else 0
        self.session.clarification = None
        self.session.stage = "generate"
        self.persist()

    def generate(self):
        from .models import TripRequest
        request = TripRequest.model_validate(self.session.pending["request"])
        budget_text = f"{request.budget:,.2f} {request.currency} for the whole group" if request.budget else f"no spending limit; estimates in {request.currency}"
        self.say(f"I'll plan {request.duration_days} days in {' → '.join(request.destinations)} for {request.travelers} traveler(s), {budget_text}, at a {request.pace} pace. "
                 + (f"Starting {request.start_date}. " if request.start_date else "Using numbered days. ")
                 + "Creating your itinerary…")
        def save_checkpoint(state):
            self.session.pending["generation"] = state
            self.persist()

        result = self.planner.plan(request, current=self.plan,
                                  instructions=self.session.pending.get("instructions", ""),
                                  checkpoint=self.session.pending.get("generation"),
                                  save_checkpoint=save_checkpoint, progress=self.say)
        if result.clarification_question or result.itinerary is None:
            self.session.clarification = result.clarification_question or result.assistant_message or "Would you prefer more days or fewer destinations?"
            self.session.stage = "clarify"
            self.persist()
            return
        roles = [RoleGeneration.model_validate(value) for value in self.session.interpretation_metadata]
        metadata = getattr(self.planner, "last_metadata", None)
        if metadata:
            roles.append(metadata)
        generation = GenerationMetadata(provider="openai", model=metadata.model if metadata else None,
                                        generated_at=metadata.generated_at if metadata else "", roles=roles)
        payload = result.itinerary.model_copy(deep=True)
        payload.assumptions = list(dict.fromkeys(payload.assumptions + self.session.pending.get("assumptions", [])))
        candidate = build_plan(payload, request, self.session.trip_id, previous=self.plan, generation=generation)
        self.commit(candidate)
        self.say(result.assistant_message or "The itinerary has been updated.")

    def commit(self, candidate):
        # Retry only persistence if a validated candidate could not be saved.
        while True:
            try:
                self.store.save_plan(candidate)
                break
            except OSError:
                self.say("The new itinerary is not yet saved. Check folder permissions, then type Retry or Exit.")
                if self.read("You: ").strip().casefold() != "retry":
                    raise LeaveSession("The new itinerary was not saved. The last successfully saved plan is preserved.")
        old = self.plan
        travelers_explicit = self.session.draft.travelers_explicit
        self.plan = candidate
        self.session.draft = RequestDraft.model_validate({**candidate.request.model_dump(),
                                                          "travelers_explicit": travelers_explicit,
                                                          "budget_per_person": False})
        self.session.stage, self.session.pending, self.session.clarification = "chat", {}, None
        self.add_history("assistant", f"Saved revision {candidate.revision}: {candidate.summary}")
        self.persist()
        self.summary()
        if old and old.request.currency == candidate.request.currency:
            difference = candidate.budget_summary.estimated_total - old.budget_summary.estimated_total
            qualifier = "known estimates" if candidate.budget_summary.partial or old.budget_summary.partial else "estimated group total"
            self.say(f"Change in {qualifier}: {difference:+,.2f} {candidate.request.currency}.")
        if old and old.request.travelers != candidate.request.travelers and old.request.budget == candidate.request.budget:
            self.say("The traveler count changed; the budget remains the same group total.")
        self.show_page(open_browser=not self.no_open)
        self.say("Make changes here in the terminal, then refresh the page to see them.")
        if old is None:
            self.say('Try “Make Day 2 more relaxed” or “What can you do?”')

    def cancel(self):
        self.session.pending, self.session.clarification = {}, None
        self.session.stage = "chat" if self.plan else "clarify"
        if self.plan:
            self.session.draft = RequestDraft.model_validate(self.plan.request.model_dump())
        self.persist()
        self.say("Pending changes canceled. Your saved plan is unchanged." if self.plan else "The trip details are saved. Tell me what to change.")

    def dispatch(self, action, reference=None):
        if action == "exit":
            raise LeaveSession()
        if action == "help":
            self.say(HELP)
        elif action in {"show", "open"}:
            if self.plan:
                self.summary() if action == "show" else self.show_page(open_browser=True)
            else:
                self.say("Your draft is saved. Complete the trip details to create the itinerary.")
        elif action in {"list", "resume", "create"}:
            self.persist()
            self.new_trip() if action == "create" else self.select_trip(reference)
        elif action == "cancel":
            self.cancel()
        elif action == "retry":
            if self.plan and self.session.pending.get("render_failed"):
                self.show_page(open_browser=not self.no_open)
            else:
                self.say("There is no failed operation to retry. Describe a change or type Help.")
        elif action == "undo":
            if not self.plan or self.plan.revision == 1:
                self.say("There is no previous revision to restore.")
            else:
                from .validation import payload_from_plan
                previous = self.store.previous_plan(self.plan)
                candidate = build_plan(payload_from_plan(previous), previous.request, self.plan.trip_id,
                                       previous=self.plan, generation=previous.generation, restored_from=previous)
                self.commit(candidate)
                self.say("Restored the previous plan as a new saved revision.")

    def chat(self):
        if self.session.stage == "clarify":
            self.say(self.session.clarification or "Tell me the trip details you want to change.")
        message = self.read("You: ").strip()
        if not message:
            return
        action = LOCAL_ACTIONS.get(message.casefold())
        if action:
            self.dispatch(action)
            return
        # Basic saved-trip access remains available during an outage.
        if message.casefold().startswith("continue "):
            reference = message[9:].strip()
            if reference.casefold().startswith("my "):
                reference = reference[3:]
            if reference.casefold().endswith(" trip"):
                reference = reference[:-5]
            self.dispatch("resume", reference)
            return
        self.add_history("user", message)
        self.session.pending["message"] = message
        self.session.stage = "interpret"
        self.persist()

    def run(self, session=None, *, resume_operation=True):
        from .openai_service import AIServiceError
        try:
            if session:
                self.session = session
                folder = self.store.directory(session.trip_id)
                self.plan = self.store.load_plan(session.trip_id) if (folder / "plan.json").exists() else None
                if self.plan and session.pending.get("base_revision", self.plan.revision) < self.plan.revision:
                    self.session.draft = RequestDraft.model_validate(self.plan.request.model_dump())
                    self.session.stage, self.session.pending, self.session.clarification = "chat", {}, None
                if self.plan and session.stage == "chat" and session.draft.duration_days is None:
                    self.session.draft = RequestDraft.model_validate(self.plan.request.model_dump())
                if self.plan:
                    self.summary()
                    self.show_page(open_browser=not self.no_open)
                if resume_operation and session.stage in {"interpret", "generate"}:
                    self.recover("An operation was interrupted. Type Retry to continue or Exit to leave.")
            else:
                self.select_trip()
            if self.plan:
                self.say('Try “Make Day 2 more relaxed” or “What can you do?”')
            while True:
                try:
                    if self.session.stage == "collect":
                        self.collect()
                    elif self.session.stage == "interpret":
                        self.interpret()
                    elif self.session.stage == "generate":
                        self.generate()
                    else:
                        self.chat()
                except (AIServiceError, ValueError) as exc:
                    self.say(str(exc))
                    self.recover("Your last saved work is preserved. Type Retry or Exit" + (", or Cancel to keep your saved plan." if self.plan else "."))
        except (KeyboardInterrupt, EOFError, LeaveSession) as exc:
            self.write("")
            if isinstance(exc, LeaveSession) and str(exc):
                self.say(str(exc))
                return
            if self.session:
                try:
                    self.store.save_session(self.session)
                    self.say("Your progress is saved. Run the app again to continue.")
                except OSError:
                    self.say("The latest progress could not be saved. Only previously saved work can be resumed.")
