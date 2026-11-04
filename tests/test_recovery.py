"""Observable recovery flows; all collaborators are deterministic and offline."""

from unittest.mock import Mock

from trip_planner.config import Config
from trip_planner.conversation import Application
from trip_planner.demo import demo_plan
from trip_planner.models import InterpreterResult, PlannerResult, RequestDraft
from trip_planner.openai_service import AIServiceError
from trip_planner.storage import Session, Store
from trip_planner.validation import payload_from_plan


def ready_result(plan):
    return InterpreterResult(
        intent="create", request_draft=RequestDraft.model_validate(plan.request.model_dump()),
        request_updates=RequestDraft(), change_instructions="", trip_reference=None,
        missing_required_fields=[], clarification_question=None, assumptions=[], assistant_message="Ready.",
    )


def planned_result(plan):
    return PlannerResult(itinerary=payload_from_plan(plan), clarification_question=None, assistant_message="Updated.")


def draft_session(plan, stage="interpret"):
    return Session(
        trip_id=plan.trip_id,
        answers={"trip_name": "Japan", "duration_days": "three days", "destinations": "Tokyo then Kyoto",
                 "budget": "75000 yen", "preferences": "temples and food"},
        prompt_index=5, stage=stage,
        draft=RequestDraft.model_validate(plan.request.model_dump()),
        pending={"request": plan.request.model_dump(mode="json"), "instructions": "Use trains", "base_revision": 0},
    )


def application(tmp_path, inputs, *, saved=False, stage="interpret", renderer=None, config=None):
    plan = demo_plan()
    store = Store(tmp_path)
    session = draft_session(plan, stage=stage)
    if saved:
        store.save_plan(plan)
        session.pending["base_revision"] = plan.revision
    store.save_session(session)
    interpreter, planner = Mock(), Mock()
    interpreter.last_metadata = planner.last_metadata = None
    interpreter.interpret.return_value = ready_result(plan)
    planner.plan.return_value = planned_result(plan)
    output = []
    answers = iter(inputs)
    app = Application(
        config or Config(), store, interpreter, planner, no_open=True,
        read=lambda label: next(answers), write=output.append,
        renderer=renderer or Mock(), browser=Mock(),
    )
    return app, session, plan, output


def test_interpreter_failure_keeps_answers_and_interrupted_stage(tmp_path):
    app, session, plan, output = application(tmp_path, ["retry", "exit"])
    app.interpreter.interpret.side_effect = AIServiceError("Connection unavailable.")
    app.run(session)
    restored = app.store.load_session(session.trip_id)
    assert restored.answers == session.answers
    assert restored.stage == "interpret"
    assert restored.pending["instructions"] == "Use trains"
    app.planner.plan.assert_not_called()
    assert not (app.store.directory(plan.trip_id) / "plan.json").exists()
    assert any("last saved work is preserved" in line for line in output)


def test_retry_interpretation_does_not_require_retyping_answers(tmp_path):
    app, session, plan, output = application(tmp_path, ["retry", "retry", "exit"])
    app.interpreter.interpret.side_effect = [AIServiceError("Temporary connection problem."), ready_result(plan)]
    app.run(session)
    assert app.interpreter.interpret.call_count == 2
    first, second = app.interpreter.interpret.call_args_list
    assert first.kwargs["answers"] == second.kwargs["answers"] == session.answers
    assert first.kwargs["message"] == second.kwargs["message"]
    app.planner.plan.assert_called_once()
    assert app.store.load_plan(plan.trip_id).revision == 1
    assert any("Revision 1 is saved" in line for line in output)


def test_retry_planning_uses_same_validated_request_without_reinterpretation(tmp_path):
    app, session, plan, output = application(tmp_path, ["retry", "retry", "exit"], stage="generate")
    app.planner.plan.side_effect = [AIServiceError("Temporary timeout."), planned_result(plan)]
    app.run(session)
    app.interpreter.interpret.assert_not_called()
    assert app.planner.plan.call_count == 2
    assert app.planner.plan.call_args_list[0] == app.planner.plan.call_args_list[1]
    assert app.store.load_plan(plan.trip_id).revision == 1


def test_failed_edit_can_be_canceled_without_changing_saved_revision(tmp_path):
    app, session, plan, output = application(tmp_path, ["retry", "cancel", "exit"], saved=True, stage="generate")
    session.pending["instructions"] = "Replace a museum with a market"
    app.store.save_session(session)
    app.planner.plan.side_effect = AIServiceError("Temporary rate limit.")
    app.run(session)
    assert app.store.load_plan(plan.trip_id) == plan
    restored = app.store.load_session(plan.trip_id)
    assert restored.stage == "chat"
    assert restored.pending == {}
    assert restored.draft.destinations == plan.request.destinations
    assert any("Pending changes canceled" in line for line in output)


def test_render_failure_retry_does_not_call_either_ai_role(tmp_path):
    renderer = Mock(side_effect=[OSError("disk failure"), None])
    app, session, plan, output = application(tmp_path, ["retry", "exit"], saved=True, stage="chat", renderer=renderer)
    app.run(session)
    app.interpreter.interpret.assert_not_called()
    app.planner.plan.assert_not_called()
    assert renderer.call_count == 2
    assert app.store.load_plan(plan.trip_id) == plan
    assert any("Your plan is saved, but the page could not be created" in line for line in output)
    assert any("Infographic:" in line for line in output)


def test_save_retry_reuses_validated_candidate_without_replanning(tmp_path, monkeypatch):
    app, session, plan, output = application(tmp_path, ["retry", "retry", "exit"], stage="generate")
    save = app.store.save_plan
    attempts = []

    def flaky_save(candidate):
        attempts.append(candidate.model_dump(mode="json"))
        if len(attempts) == 1:
            raise PermissionError("read-only folder")
        save(candidate)

    monkeypatch.setattr(app.store, "save_plan", flaky_save)
    app.run(session)
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    app.planner.plan.assert_called_once()
    assert app.store.load_plan(plan.trip_id).revision == 1
    assert any("new itinerary is not yet saved" in line for line in output)


def test_save_failure_exit_never_claims_candidate_was_saved(tmp_path, monkeypatch):
    app, session, plan, output = application(tmp_path, ["retry", "exit"], stage="generate")
    monkeypatch.setattr(app.store, "save_plan", Mock(side_effect=PermissionError("read-only folder")))
    app.run(session)
    assert not (app.store.directory(plan.trip_id) / "plan.json").exists()
    assert not any("Revision 1 is saved" in line for line in output)
    assert any("new itinerary was not saved" in line for line in output)
    assert app.store.load_session(plan.trip_id).stage == "generate"
    app.planner.plan.assert_called_once()


def test_question_during_pending_edit_preserves_pending_work(tmp_path):
    app, session, plan, output = application(tmp_path, [], saved=True, stage="interpret")
    app.session, app.plan = session, plan
    session.clarification = "Add a day or remove Kyoto?"
    session.pending["instructions"] = "Make Kyoto less rushed"
    session.pending["message"] = "Would another day help?"
    answer = ready_result(plan).model_copy(update={"intent": "question", "assistant_message": "Yes, another day allows a slower Kyoto visit."})
    app.interpreter.interpret.return_value = answer
    app.interpret()
    assert app.session.pending["instructions"] == "Make Kyoto less rushed"
    assert app.session.clarification == "Add a day or remove Kyoto?"
    assert app.session.stage == "clarify"
    assert app.store.load_plan(plan.trip_id) == plan
    app.planner.plan.assert_not_called()
    assert any("another day allows" in line for line in output)


def test_local_show_help_and_exit_work_without_configuration_or_network(tmp_path):
    app, session, plan, output = application(tmp_path, ["show my plan", "help", "exit"], saved=True, stage="chat", config=Config())
    app.interpreter.interpret.side_effect = AssertionError("No network calls allowed")
    app.planner.plan.side_effect = AssertionError("No network calls allowed")
    app.run(session)
    app.interpreter.interpret.assert_not_called()
    app.planner.plan.assert_not_called()
    assert any("Estimated group total" in line for line in output)
    assert any("Undo my last change" in line for line in output)


def test_local_show_available_during_failed_edit_recovery(tmp_path):
    app, session, plan, output = application(tmp_path, ["retry", "show my plan", "cancel", "exit"], saved=True, stage="generate")
    app.planner.plan.side_effect = AIServiceError("Network outage.")
    app.run(session)
    assert app.store.load_plan(plan.trip_id) == plan
    assert sum("Estimated group total" in line for line in output) == 2
    app.interpreter.interpret.assert_not_called()


def test_resume_reconciles_plan_committed_before_session_write(tmp_path):
    app, session, plan, output = application(tmp_path, ["exit"], saved=True, stage="generate")
    # Simulate plan.json committed successfully, then interrupted session.json write.
    session.pending["base_revision"] = 0
    app.store.save_session(session)
    app.run(session)
    restored = app.store.load_session(plan.trip_id)
    assert restored.stage == "chat"
    assert restored.pending == {}
    assert not any("operation was interrupted" in line for line in output)
    app.interpreter.interpret.assert_not_called()
    app.planner.plan.assert_not_called()
