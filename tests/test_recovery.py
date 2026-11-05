"""Offline regressions for resumable generation and the real SDK stream parser."""

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from trip_planner.config import Config, ConfigurationError
from trip_planner.conversation import Application
from trip_planner.demo import demo_plan
from trip_planner.interpreter import Interpreter
from trip_planner.models import (
    DayOutline, DayResult, InterpreterResult, PlanningOutline,
    RequestDraft, RoleGeneration, TokenUsage,
)
from trip_planner.openai_service import AIServiceError, OpenAIService
from trip_planner.planner import Planner
from trip_planner.storage import Session, Store
from trip_planner.validation import build_plan, payload_from_plan, validate_day_prefix


CONFIG = Config(api_key="test-key", extractor_model="test-model", planner_model="test-model", planner_workers=1)


def fixtures():
    plan = demo_plan()
    payload = payload_from_plan(plan)
    outline = PlanningOutline(
        summary=payload.summary,
        days=[DayOutline(day_number=day.day_number, title=day.title,
                         destinations=([plan.request.destinations[0]] if day.day_number < 3
                                       else plan.request.destinations),
                         instructions=day.summary, reuse_existing=False,
                         start_location="Tokyo", end_location="Tokyo" if day.day_number < 3 else "Kyoto",
                         overnight_base="Tokyo" if day.day_number < 3 else "Kyoto",
                         incoming_transfer=None if day.day_number < 3 else day.schedule[0].travel) for day in payload.days],
        assumptions=payload.assumptions, warnings=payload.warnings,
        clarification_question=None, assistant_message="Done",
    )
    return plan, payload, outline


class ScriptedService:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []
        self.last_metadata = None

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.results)
        if isinstance(value, Exception):
            raise value
        self.last_metadata = RoleGeneration(role=kwargs["role"], provider="openai", model="test-model",
                                            generated_at="2026-11-05T12:00:00+00:00",
                                            usage=TokenUsage(input_tokens=10, output_tokens=20, total_tokens=30))
        return value.model_copy(deep=True)


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.payload, self.outline = fixtures()
        self.saved = None

    def save(self, state):
        self.saved = deepcopy(state)

    def test_timeout_resumes_next_day_in_a_new_planner(self):
        first = ScriptedService([self.outline, DayResult(day=self.payload.days[0], clarification_question=None),
                                 AIServiceError("timeout")])
        with self.assertRaisesRegex(AIServiceError, "timeout"):
            Planner(CONFIG, first).plan(self.plan.request, save_checkpoint=self.save)
        self.assertEqual(len(self.saved["days"]), 1)
        second = ScriptedService([DayResult(day=day, clarification_question=None) for day in self.payload.days[1:]])
        planner = Planner(CONFIG, second)
        result = planner.plan(self.plan.request, checkpoint=self.saved, save_checkpoint=self.save)
        self.assertEqual([call["data"]["day_to_generate"]["day_number"] for call in second.calls], [2, 3])
        self.assertEqual(len(result.itinerary.days), 3)
        self.assertEqual(planner.last_metadata.usage.total_tokens, 120)
        build_plan(result.itinerary, self.plan.request, "resumed")

    def test_complete_checkpoint_needs_no_new_requests(self):
        service = ScriptedService([self.outline] + [DayResult(day=day, clarification_question=None) for day in self.payload.days])
        Planner(CONFIG, service).plan(self.plan.request, save_checkpoint=self.save)
        result = Planner(CONFIG, ScriptedService([])).plan(self.plan.request, checkpoint=self.saved)
        self.assertEqual(result.itinerary, self.payload)

    def test_changed_instructions_invalidate_checkpoint(self):
        service = ScriptedService([self.outline, DayResult(day=self.payload.days[0], clarification_question=None), AIServiceError("timeout")])
        with self.assertRaises(AIServiceError):
            Planner(CONFIG, service).plan(self.plan.request, save_checkpoint=self.save)
        next_service = ScriptedService([self.outline] + [DayResult(day=day, clarification_question=None) for day in self.payload.days])
        Planner(CONFIG, next_service).plan(self.plan.request, instructions="Change Day 1", checkpoint=self.saved)
        self.assertIs(next_service.calls[0]["response_model"], PlanningOutline)

    def test_edit_only_generates_changed_day(self):
        self.outline.days[0].reuse_existing = True
        self.outline.days[2].reuse_existing = True
        changed = self.payload.days[1].model_copy(deep=True)
        changed.title = "More relaxed"
        service = ScriptedService([self.outline, DayResult(day=changed, clarification_question=None)])
        result = Planner(CONFIG, service).plan(self.plan.request, current=self.plan, instructions="Relax Day 2")
        self.assertEqual(len(service.calls), 2)
        candidate = build_plan(result.itinerary, self.plan.request, self.plan.trip_id, previous=self.plan)
        self.assertEqual(candidate.days[0], self.plan.days[0])
        self.assertEqual(candidate.days[2], self.plan.days[2])

    def test_constraint_change_prevents_reusing_stale_days(self):
        request = self.plan.request.model_copy(update={"travelers": 2})
        for day in self.outline.days:
            day.reuse_existing = True
        service = ScriptedService([self.outline] + [DayResult(day=day, clarification_question=None) for day in self.payload.days])
        Planner(CONFIG, service).plan(request, current=self.plan)
        self.assertEqual(len(service.calls), 4)

    def test_transport_change_keeps_checkpoint(self):
        service = ScriptedService([self.outline, DayResult(day=self.payload.days[0], clarification_question=None), AIServiceError("timeout")])
        with self.assertRaises(AIServiceError):
            Planner(CONFIG, service).plan(self.plan.request, save_checkpoint=self.save)
        retry = ScriptedService([DayResult(day=day, clarification_question=None) for day in self.payload.days[1:]])
        Planner(replace(CONFIG, timeout=180, planner_max_output_tokens=9000), retry).plan(self.plan.request, checkpoint=self.saved)
        self.assertEqual(len(retry.calls), 2)

    def test_invalid_day_is_repaired_without_repeating_previous_days(self):
        broken = self.payload.days[1].model_copy(deep=True)
        broken.schedule[0].duration_minutes += 1
        service = ScriptedService([self.outline,
                                  DayResult(day=self.payload.days[0], clarification_question=None),
                                  DayResult(day=broken, clarification_question=None),
                                  DayResult(day=self.payload.days[1], clarification_question=None),
                                  DayResult(day=self.payload.days[2], clarification_question=None)])
        Planner(CONFIG, service).plan(self.plan.request, save_checkpoint=self.save)
        self.assertEqual([call["data"]["day_to_generate"]["day_number"] for call in service.calls[1:]], [1, 2, 2, 3])
        self.assertIn("inconsistent", service.calls[3]["data"]["validation_feedback"])

    def test_interruption_during_repair_preserves_feedback(self):
        broken = self.payload.days[0].model_copy(deep=True)
        broken.schedule[0].cost.currency = "USD"
        service = ScriptedService([self.outline, DayResult(day=broken, clarification_question=None), AIServiceError("timeout")])
        with self.assertRaises(AIServiceError):
            Planner(CONFIG, service).plan(self.plan.request, save_checkpoint=self.save)
        self.assertIn("reporting currency", self.saved["invalid_day"]["feedback"])
        self.saved["invalid_day"]["feedback"] = "Older, unhelpful validation feedback"
        retry = ScriptedService([DayResult(day=self.payload.days[1], clarification_question=None),
                                 DayResult(day=self.payload.days[2], clarification_question=None),
                                 DayResult(day=self.payload.days[0], clarification_question=None)])
        Planner(CONFIG, retry).plan(self.plan.request, checkpoint=self.saved)
        self.assertEqual(retry.calls[-1]["data"]["candidate_to_repair"], broken.model_dump(mode="json"))
        self.assertIn("reporting currency", retry.calls[-1]["data"]["validation_feedback"])

    def test_country_trip_feedback_identifies_missing_visit_labels(self):
        request = self.plan.request.model_copy(update={"destinations": ["Japan"], "duration_days": 1})
        day = self.payload.days[0].model_copy(deep=True)
        day.destinations = ["Japan"]
        with self.assertRaisesRegex(ValueError, "Missing visit labels: Japan"):
            validate_day_prefix([day], request)
        for item in day.schedule:
            if item.location:
                item.location += ", Japan"
        validate_day_prefix([day], request)

    def test_repeated_invalid_day_stops_after_one_repair(self):
        broken = self.payload.days[0].model_copy(deep=True)
        broken.schedule[0].duration_minutes += 1
        service = ScriptedService([self.outline] + [DayResult(day=broken, clarification_question=None)] * 2)
        with self.assertRaisesRegex(AIServiceError, "still needs correction"):
            Planner(CONFIG, service).plan(self.plan.request, save_checkpoint=self.save)
        self.assertEqual(len(service.calls), 3)
        self.assertEqual(self.saved["days"], [])

    def test_outline_clarification_does_not_generate_days(self):
        self.outline.clarification_question = "Add a day?"
        self.outline.days = []
        service = ScriptedService([self.outline])
        result = Planner(CONFIG, service).plan(self.plan.request)
        self.assertIsNone(result.itinerary)
        self.assertEqual(len(service.calls), 1)

    def test_invalid_outline_gets_one_bounded_repair(self):
        self.outline.days = []
        service = ScriptedService([self.outline, self.outline])
        with self.assertRaisesRegex(AIServiceError, "outline"):
            Planner(CONFIG, service).plan(self.plan.request)
        self.assertEqual(len(service.calls), 2)

    def test_dates_and_cross_day_transfers_are_checked(self):
        days = deepcopy(self.payload.days)
        days[1].date = self.plan.created_at[:10]
        with self.assertRaisesRegex(ValueError, "dates"):
            validate_day_prefix(days[:2], self.plan.request)
        days = deepcopy(self.payload.days)
        days[2].schedule = days[2].schedule[1:]
        with self.assertRaisesRegex(ValueError, "intercity transfer"):
            validate_day_prefix(days, self.plan.request)

    def test_application_persists_partial_days_then_commits_once(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            app = Application(CONFIG, store, None, Planner(CONFIG, ScriptedService([
                self.outline, DayResult(day=self.payload.days[0], clarification_question=None), AIServiceError("timeout")
            ])), no_open=True, write=lambda value: None)
            app.session = Session(stage="generate", pending={"request": self.plan.request.model_dump(mode="json")})
            store.save_session(app.session)
            with self.assertRaises(AIServiceError):
                app.generate()
            session = store.load_session(app.session.trip_id)
            self.assertEqual(len(session.pending["generation"]["days"]), 1)
            self.assertFalse((store.directory(session.trip_id) / "plan.json").exists())
            app.session = session
            app.planner = Planner(CONFIG, ScriptedService([DayResult(day=day, clarification_question=None) for day in self.payload.days[1:]]))
            app.generate()
            self.assertEqual(store.load_plan(session.trip_id).revision, 1)
            self.assertEqual(store.load_session(session.trip_id).pending, {})
            self.assertTrue((store.directory(session.trip_id) / "itinerary.html").exists())

    def test_interpreter_excludes_checkpoint_but_keeps_question_context(self):
        answer = InterpreterResult(intent="question", request_draft=RequestDraft(), request_updates=RequestDraft(),
                                   change_instructions="", trip_reference=None, missing_required_fields=[],
                                   clarification_question=None, assumptions=[], assistant_message="Estimate")
        service = ScriptedService([answer])
        Interpreter(CONFIG, service).interpret(answers={}, draft=RequestDraft(), plan=self.plan,
                                              pending={"instructions": "Relax Day 2", "generation": {"large": "checkpoint"}},
                                              history=[{"role": "user", "content": "question"}] * 30)
        data = service.calls[0]["data"]
        self.assertNotIn("generation", data["pending_edit"])
        self.assertNotIn("generation", data["active_plan"])
        self.assertEqual(data["active_plan"]["budget_summary"]["estimated_total"], self.plan.budget_summary.estimated_total)
        self.assertEqual(len(data["recent_conversation"]), 12)


class ConfigurationTests(unittest.TestCase):
    def test_loads_timing_and_output_settings_and_environment_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("OPENAI_TIMEOUT_SECONDS=120\nOPENAI_MAX_RETRIES=1\nOPENAI_REQUEST_DEADLINE_SECONDS=240\nOPENAI_PLANNER_MAX_OUTPUT_TOKENS=7000\n")
            with patch.dict(os.environ, {"OPENAI_TIMEOUT_SECONDS": "45"}, clear=True):
                config = Config.load(env)
            self.assertEqual((config.timeout, config.max_retries, config.request_deadline, config.planner_max_output_tokens), (45, 1, 240, 7000))

    def test_rejects_invalid_settings_without_echoing_values(self):
        for setting, value in [("OPENAI_TIMEOUT_SECONDS", "nan"), ("OPENAI_MAX_RETRIES", "4"),
                               ("OPENAI_TIMEOUT_SECONDS", "secret-value"), ("OPENAI_PLANNER_MAX_OUTPUT_TOKENS", "0")]:
            with self.subTest(setting=setting, value=value), tempfile.TemporaryDirectory() as folder:
                with patch.dict(os.environ, {setting: value}, clear=True):
                    with self.assertRaises(ConfigurationError) as raised:
                        Config.load(Path(folder) / "missing.env")
                self.assertNotIn(value, str(raised.exception))


def sdk_client(events, requests):
    def handle(request):
        requests.append(json.loads(request.content))
        body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
    return OpenAI(api_key="test-key", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def stream_events(status="completed", text=None, refusal=False):
    response = {"id": "resp_test", "created_at": 1, "object": "response", "model": "test-model",
                "status": "in_progress", "output": [], "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}}
    created = {"type": "response.created", "response": deepcopy(response), "sequence_number": 0}
    response["status"] = status
    if status == "completed":
        content = {"type": "refusal", "refusal": "No"} if refusal else {"type": "output_text", "text": text, "annotations": []}
        response["output"] = [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed", "content": [content]}]
    elif status == "incomplete":
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    return [created, {"type": f"response.{status}", "response": response, "sequence_number": 1}]


class StreamingTests(unittest.TestCase):
    def test_real_sdk_parses_structured_stream_without_storing(self):
        requests = []
        result = DayResult(day=None, clarification_question="Add a day?")
        client = sdk_client(stream_events(text=result.model_dump_json()), requests)
        with client:
            service = OpenAIService(CONFIG, client)
            self.assertEqual(service.parse(role="planner", prompt="test", data={}, response_model=DayResult), result)
        self.assertTrue(requests[0]["stream"])
        self.assertFalse(requests[0]["store"])
        self.assertEqual(requests[0]["max_output_tokens"], CONFIG.planner_max_output_tokens)
        self.assertEqual(service.last_metadata.usage.total_tokens, 5)

    def test_incomplete_stream_gives_actionable_output_limit(self):
        with sdk_client(stream_events(status="incomplete"), []) as client:
            with self.assertRaisesRegex(AIServiceError, "OPENAI_EXTRACTOR_MAX_OUTPUT_TOKENS"):
                OpenAIService(CONFIG, client).parse(role="interpreter", prompt="test", data={}, response_model=DayResult)

    def test_refusal_and_invalid_json_are_safe(self):
        for events, message in [(stream_events(refusal=True), "declined"),
                                (stream_events(text="invalid-json-secret"), "invalid structured")]:
            with self.subTest(message=message), sdk_client(events, []) as client:
                with self.assertRaisesRegex(AIServiceError, message) as raised:
                    OpenAIService(CONFIG, client).parse(role="planner", prompt="test", data={}, response_model=DayResult)
                self.assertNotIn("invalid-json-secret", str(raised.exception))

    def test_early_stream_end_is_recoverable(self):
        with sdk_client(stream_events()[:1], []) as client:
            with self.assertRaisesRegex(AIServiceError, "ended early"):
                OpenAIService(CONFIG, client).parse(role="planner", prompt="test", data={}, response_model=DayResult)

    def test_midstream_read_timeout_is_caught(self):
        class BrokenBody(httpx.SyncByteStream):
            def __iter__(self):
                yield b": connected\n\n"
                raise httpx.ReadTimeout("provider-secret")
        client = OpenAI(api_key="test-key", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=BrokenBody())
        )))
        with client, self.assertRaisesRegex(AIServiceError, "stopped responding") as raised:
            OpenAIService(CONFIG, client).parse(role="planner", prompt="test", data={}, response_model=DayResult)
        self.assertNotIn("provider-secret", str(raised.exception))

    def test_deadline_closes_stream(self):
        with sdk_client(stream_events()[:1], []) as client:
            with patch("trip_planner.openai_service.monotonic", side_effect=[0, 301]):
                with self.assertRaisesRegex(AIServiceError, "time limit"):
                    OpenAIService(CONFIG, client).parse(role="planner", prompt="test", data={}, response_model=DayResult)


if __name__ == "__main__":
    unittest.main()
