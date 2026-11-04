from unittest.mock import Mock

from trip_planner.config import Config
from trip_planner.conversation import Application, PROMPTS
from trip_planner.demo import demo_plan
from trip_planner.models import InterpreterResult, PlannerResult, RequestDraft
from trip_planner.storage import Session, Store
from trip_planner.validation import payload_from_plan


def interpretation(intent="create", draft=None, **kwargs):
    return InterpreterResult(intent=intent, request_draft=draft or RequestDraft(),
                             request_updates=kwargs.pop("request_updates", RequestDraft()),
                             change_instructions=kwargs.pop("change_instructions", ""),
                             trip_reference=None, missing_required_fields=[],
                             clarification_question=kwargs.pop("clarification_question", None),
                             assumptions=[], assistant_message=kwargs.pop("assistant_message", "Ready."), **kwargs)


def application(tmp_path, inputs=(), responses=()):
    source = demo_plan()
    interpreter = Mock(last_metadata=None)
    interpreter.interpret.side_effect = list(responses)
    planner = Mock(last_metadata=None)
    planner.plan.return_value = PlannerResult(itinerary=payload_from_plan(source), clarification_question=None,
                                             assistant_message="A food and culture itinerary.")
    prompts, output = [], []
    values = iter(inputs)

    def read(prompt):
        prompts.append(prompt)
        try:
            return next(values)
        except StopIteration:
            raise EOFError

    app = Application(Config(api_key="test", extractor_model="test", planner_model="test"),
                      Store(tmp_path), interpreter, planner, no_open=True,
                      read=read, write=output.append, browser=Mock())
    return app, prompts, output


def sample_draft():
    return RequestDraft.model_validate(demo_plan().request.model_dump())


def save_fixture(app, name=None):
    plan = demo_plan()
    if name:
        plan.request.trip_name = name
    app.store.save_plan(plan)
    session = Session(trip_id=plan.trip_id, stage="chat", draft=RequestDraft.model_validate(plan.request.model_dump()))
    app.store.save_session(session)
    return plan, session


def test_first_use_complete_pipeline_no_approval_and_two_role_handoff(tmp_path):
    answers = ["Japan", "three days", "Tokyo then Kyoto", "80000 yen for the group", "solo; local food", "exit"]
    app, prompts, output = application(tmp_path, answers, [interpretation(draft=sample_draft())])
    app.run()
    assert prompts[:5] == [label for _, label, _ in PROMPTS]
    extraction = app.interpreter.interpret.call_args.kwargs
    assert len(extraction["answers"]) == 5
    assert extraction["answers"]["duration_days"] == "three days"
    request = app.planner.plan.call_args.args[0]
    assert request.duration_days == 3
    assert request.destinations == demo_plan().request.destinations
    assert app.plan.revision == 1
    assert (app.store.directory(app.plan.trip_id) / "itinerary.html").exists()
    assert "is saved" in "\n".join(output)
    app.browser.assert_not_called()


def test_collection_skips_required_reprompt_help_and_back(tmp_path):
    app, prompts, output = application(tmp_path, ["back", "", "", "a week", "back", "five days", "東京", "skip", "help", "", "exit"])
    app.new_trip()
    app.collect()
    assert app.session.answers == {"trip_name": "", "duration_days": "five days", "destinations": "東京", "budget": "", "preferences": ""}
    assert app.session.skipped == ["trip_name", "budget", "preferences"]
    assert app.session.stage == "interpret"
    assert app.interpreter.interpret.call_count == 0
    assert app.planner.plan.call_count == 0
    assert any("There is no earlier" in line for line in output)
    assert any("How many days?" in line for line in output)


def test_back_preserves_other_completed_answers(tmp_path):
    app, _, _ = application(tmp_path, ["back", "six days"])
    app.session = Session(answers={"trip_name": "Japan", "duration_days": "five days", "destinations": "東京", "budget": "100000 JPY"}, prompt_index=4)
    # Back from preferences changes the existing budget and returns to preferences.
    app.read = Mock(side_effect=["back", "120000 JPY", "skip"])
    app.collect()
    assert app.session.answers["duration_days"] == "five days"
    assert app.session.answers["destinations"] == "東京"
    assert app.session.answers["budget"] == "120000 JPY"


def test_collection_restart_goes_to_next_unanswered_prompt(tmp_path):
    app, _, _ = application(tmp_path, ["Japan", "exit"])
    app.run()
    trips = app.store.list_trips()
    assert len(trips) == 1 and trips[0]["status"] == "Draft"
    resumed, prompts, _ = application(tmp_path, ["2", "three days", "Tokyo then Kyoto", "", "", "exit"], [interpretation(draft=sample_draft())])
    resumed.run()
    assert prompts[1] == "Days: "
    assert resumed.plan.revision == 1
    assert resumed.session.answers["trip_name"] == "Japan"


def test_ambiguity_keeps_answers_and_does_not_plan(tmp_path):
    draft = RequestDraft(duration_days=3, destinations=["Tokyo"], budget=500)
    first = interpretation(draft=draft, clarification_question="Does 500 mean USD or another currency?")
    app, _, output = application(tmp_path, ["Japan", "three days", "Tokyo", "500", "", "exit"], [first])
    app.run()
    app.planner.plan.assert_not_called()
    assert app.session.stage == "clarify"
    assert app.session.answers["budget"] == "500"
    assert any("Does 500" in line for line in output)


def test_clarification_resumes_without_reasking_resolved_answers(tmp_path):
    first = sample_draft().model_copy(update={"currency": None, "budget": 80000})
    second = first.model_copy(update={"currency": "JPY"})
    app, prompts, _ = application(tmp_path, ["Japan", "three days", "Tokyo then Kyoto", "80000", "", "JPY", "exit"],
                                  [interpretation(draft=first), interpretation(draft=second)])
    app.run()
    assert app.planner.plan.call_count == 1
    assert prompts.count("Budget (optional): ") == 1
    assert app.interpreter.interpret.call_args.kwargs["message"] == "JPY"


def test_resume_by_name_is_offline_and_does_not_regenerate(tmp_path):
    app, _, output = application(tmp_path, ["Japan", "show my plan", "help", "exit"])
    plan, _ = save_fixture(app)
    app.run()
    app.interpreter.interpret.assert_not_called()
    app.planner.plan.assert_not_called()
    assert app.plan.trip_id == plan.trip_id
    app.browser.assert_not_called()
    assert any("Revision 1 is saved" in line for line in output)


def test_new_trip_preserves_existing_plan(tmp_path):
    app, _, _ = application(tmp_path, ["1", "Another trip", "exit"])
    plan, _ = save_fixture(app)
    app.run()
    assert app.store.load_plan(plan.trip_id) == plan
    trips = app.store.list_trips()
    assert len(trips) == 2
    assert {entry["status"] for entry in trips} == {"Draft", "Plan"}


def test_question_and_hypothetical_leave_revision_unchanged(tmp_path):
    result = interpretation("question", assistant_message="Another day would allow more rest. Shall we consider it?")
    app, _, output = application(tmp_path, ["2", "Would another day help?", "exit"], [result])
    plan, _ = save_fixture(app)
    app.run()
    assert app.store.load_plan(plan.trip_id).revision == 1
    app.planner.plan.assert_not_called()
    assert any("Another day" in line for line in output)


def test_edit_preserves_unaffected_days_ids_and_undo_restores_as_new_revision(tmp_path):
    edit = interpretation("edit", change_instructions="Make Day 2 quieter.")
    app, _, _ = application(tmp_path, ["2", "Make Day 2 quieter", "undo my last change", "exit"], [edit])
    plan, _ = save_fixture(app)
    payload = payload_from_plan(plan)
    payload.days[1].title = "A quiet afternoon"
    app.planner.plan.return_value = PlannerResult(itinerary=payload, clarification_question=None, assistant_message="Day 2 is quieter.")
    app.run()
    revised = app.store.load_plan(plan.trip_id)
    assert revised.revision == 3
    assert revised.created_at == plan.created_at
    assert revised.days == plan.days
    assert app.planner.plan.call_count == 1
    revision2 = app.store.directory(plan.trip_id) / "revisions" / "0002.json"
    assert revision2.exists()


def test_traveler_edit_keeps_group_budget(tmp_path):
    edit = interpretation("edit", request_updates=RequestDraft(travelers=2), change_instructions="Two travelers instead of one.")
    app, _, output = application(tmp_path, ["2", "Add another person", "exit"], [edit])
    original, _ = save_fixture(app)
    app.run()
    assert app.plan.request.travelers == 2
    assert app.plan.request.budget == original.request.budget
    assert any("same group total" in line for line in output)


def test_clearing_budget_does_not_clear_other_constraints(tmp_path):
    edit = interpretation("edit", clear_fields=["budget"], change_instructions="Remove the spending limit.")
    app, _, _ = application(tmp_path, ["2", "Remove the spending limit", "exit"], [edit])
    original, _ = save_fixture(app)
    app.run()
    assert app.plan.request.budget is None
    assert app.plan.request.duration_days == original.request.duration_days
    assert app.plan.request.destinations == original.request.destinations


def test_ambiguous_saved_name_asks_number(tmp_path):
    app, prompts, output = application(tmp_path, ["Japan", "2", "exit"])
    first, _ = save_fixture(app, "Japan one")
    second = first.model_copy(update={"trip_id": "other-trip"}, deep=True)
    second.request.trip_name = "Japan two"
    app.store.save_plan(second)
    app.store.save_session(Session(trip_id=second.trip_id, stage="chat"))
    app.run()
    assert any("Several trips match" in line for line in output)
    assert app.plan is not None


def test_resume_opens_page_without_planning(tmp_path):
    app, _, _ = application(tmp_path, ["2", "exit"])
    save_fixture(app)
    app.no_open = False
    app.run()
    app.browser.assert_called_once()
    assert app.browser.call_args.args[0].startswith("file:")
    app.planner.plan.assert_not_called()


def test_natural_new_trip_intent_preserves_existing_plan(tmp_path):
    app, prompts, _ = application(tmp_path, ["2", "Let's plan a different trip", "Spain", "exit"], [interpretation("create")])
    original, _ = save_fixture(app)
    app.run()
    assert app.store.load_plan(original.trip_id) == original
    assert len(app.store.list_trips()) == 2
    assert "Trip name (optional): " in prompts
    app.planner.plan.assert_not_called()


def test_pending_edit_short_reply_keeps_instructions_and_completes_revision(tmp_path):
    edit = interpretation("edit", change_instructions="Make Kyoto less rushed.")
    follow_up = interpretation("edit", request_updates=RequestDraft(duration_days=4), change_instructions="Add a day.")
    app, _, _ = application(tmp_path, ["2", "Make Kyoto less rushed", "Add a day", "exit"], [edit, follow_up])
    original, _ = save_fixture(app)
    payload = payload_from_plan(original)
    extra = payload.days[-1].model_copy(deep=True)
    extra.day_number, extra.title, extra.destinations = 4, "A slower day in Kyoto", ["Kyoto"]
    extra.schedule = extra.schedule[1:]  # Already in Kyoto; no second intercity journey.
    for item in extra.schedule:
        item.id = None
    payload.days.append(extra)
    app.planner.plan.side_effect = [
        PlannerResult(itinerary=None, clarification_question="Add a day or remove a city?", assistant_message="More time is needed."),
        PlannerResult(itinerary=payload, clarification_question=None, assistant_message="Kyoto has another day."),
    ]
    app.run()
    assert app.plan.revision == 2 and app.plan.request.duration_days == 4
    instructions = app.planner.plan.call_args.kwargs["instructions"]
    assert "Make Kyoto less rushed" in instructions and "Add a day" in instructions
    assert app.session.pending == {}
