"""Concurrency, checkpoint ordering, and reasoning options without network access."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from threading import Barrier, Event, Lock, get_ident, local
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from trip_planner.config import Config, ConfigurationError
from trip_planner.demo import _transfer
from trip_planner.models import DayResult, RoleGeneration, TokenUsage
from trip_planner.openai_service import AIServiceError, OpenAIService
from trip_planner.planner import Planner
from trip_planner.validation import build_plan, validate_day_prefix
from test_recovery import CONFIG, fixtures, sdk_client, stream_events


class ConcurrentService:
    def __init__(self, *, barrier=None, fail=(), gate=None, broken_transfer=False):
        self.plan, self.payload, self.outline = fixtures()
        self.barrier, self.fail, self.gate = barrier, set(fail), gate
        self.broken_transfer = broken_transfer
        self.lock, self.metadata = Lock(), local()
        self.calls = []
        self.active = self.peak = 0

    @property
    def last_metadata(self):
        return getattr(self.metadata, "value", None)

    def parse(self, **kwargs):
        number = kwargs["data"].get("day_to_generate", {}).get("day_number", 0)
        with self.lock:
            self.calls.append(kwargs)
            attempt = sum(call["data"].get("day_to_generate", {}).get("day_number", 0) == number for call in self.calls)
            if number:
                self.active += 1
                self.peak = max(self.peak, self.active)
        try:
            if number and self.barrier and attempt == 1:
                self.barrier.wait(timeout=3)
            if number == 1 and self.gate:
                if not self.gate.wait(timeout=3):
                    raise AssertionError("Day 3 was not checkpointed while Day 1 was running")
            if number in self.fail:
                raise AIServiceError(f"Day {number} timeout")
            self.metadata.value = RoleGeneration(role="planner", provider="test", model="test-model",
                                                  generated_at="2026-11-05T12:00:00+00:00", reasoning_effort="low",
                                                  usage=TokenUsage(input_tokens=number + 1, output_tokens=number + 1,
                                                                   total_tokens=number + 1, reasoning_tokens=number))
            if not number:
                return self.outline.model_copy(deep=True)
            if kwargs.get("progress"):
                kwargs["progress"]("working")
            day = self.payload.days[number - 1].model_copy(deep=True)
            if number == 3 and self.broken_transfer and attempt == 1:
                day.schedule.pop(0)
            return DayResult(day=day, clarification_question=None)
        finally:
            if number:
                with self.lock:
                    self.active -= 1


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.config = replace(CONFIG, planner_workers=3)
        self.saved = None
        self.snapshots = []

    def save(self, state):
        self.saved = deepcopy(state)
        self.snapshots.append(deepcopy(state))

    def test_three_calls_overlap_and_out_of_order_results_are_saved(self):
        gate = Event()
        service = ConcurrentService(barrier=Barrier(3), gate=gate)
        main_thread = get_ident()
        def save(state):
            self.assertEqual(get_ident(), main_thread)
            self.save(state)
            if "3" in state["ready_days"]:
                gate.set()
        def progress(message):
            self.assertEqual(get_ident(), main_thread)
        planner = Planner(self.config, service)
        result = planner.plan(service.plan.request, save_checkpoint=save, progress=progress)
        self.assertEqual(service.peak, 3)
        self.assertTrue(any("3" in state["ready_days"] and "1" not in state["ready_days"] for state in self.snapshots))
        self.assertEqual([day.day_number for day in result.itinerary.days], [1, 2, 3])
        self.assertEqual(planner.last_metadata.usage.total_tokens, 10)
        self.assertEqual(planner.last_metadata.usage.reasoning_tokens, 6)
        build_plan(result.itinerary, service.plan.request, "parallel")

    def test_failed_first_day_keeps_other_completed_days_on_restart(self):
        service = ConcurrentService(barrier=Barrier(3), fail={1})
        with self.assertRaisesRegex(AIServiceError, "timeout"):
            Planner(self.config, service).plan(service.plan.request, save_checkpoint=self.save)
        self.assertEqual(self.saved["days"], [])
        self.assertEqual(set(self.saved["ready_days"]), {"2", "3"})
        retry = ConcurrentService()
        result = Planner(self.config, retry).plan(service.plan.request, checkpoint=self.saved, save_checkpoint=self.save)
        self.assertEqual([call["data"]["day_to_generate"]["day_number"] for call in retry.calls], [1])
        self.assertEqual(len(result.itinerary.days), 3)

    def test_worker_limit_can_disable_concurrency(self):
        service = ConcurrentService()
        Planner(replace(self.config, planner_workers=1), service).plan(service.plan.request)
        self.assertEqual(service.peak, 1)

    def test_independent_repairs_overlap_inside_the_worker_limit(self):
        repair_barrier = Barrier(3)
        class Service(ConcurrentService):
            def parse(inner, **kwargs):
                number = kwargs["data"].get("day_to_generate", {}).get("day_number")
                repairing = bool(kwargs["data"].get("validation_feedback"))
                if number and repairing:
                    repair_barrier.wait(timeout=3)
                result = super(Service, inner).parse(**kwargs)
                if number and not repairing:
                    result.day.schedule[0].duration_minutes += 1
                return result
        service = Service(barrier=Barrier(3))
        planner = Planner(self.config, service)
        result = planner.plan(service.plan.request, save_checkpoint=self.save)
        self.assertEqual(len(service.calls), 7)
        self.assertEqual(planner.last_metadata.usage.total_tokens, 19)
        build_plan(result.itinerary, service.plan.request, "parallel-repairs")

    def test_cross_day_repair_does_not_regenerate_good_neighbors(self):
        service = ConcurrentService(barrier=Barrier(3), broken_transfer=True)
        result = Planner(self.config, service).plan(service.plan.request, save_checkpoint=self.save)
        numbers = [call["data"].get("day_to_generate", {}).get("day_number") for call in service.calls]
        self.assertEqual(numbers.count(1), 1)
        self.assertEqual(numbers.count(2), 1)
        self.assertEqual(numbers.count(3), 2)
        self.assertEqual(service.calls[-1]["data"]["previous_day_outline"]["day_number"], 2)
        build_plan(result.itinerary, service.plan.request, "repaired")

    def test_cross_day_overlap_is_repaired_with_fixed_previous_schedule(self):
        class Service(ConcurrentService):
            def parse(inner, **kwargs):
                result = super(Service, inner).parse(**kwargs)
                number = kwargs["data"].get("day_to_generate", {}).get("day_number")
                if number == 1:
                    item = result.day.schedule[-1]
                    item.end_time, item.end_day_offset, item.duration_minutes = "10:00", 1, 990
                elif number == 2 and kwargs["data"].get("validation_feedback"):
                    for item in result.day.schedule:
                        for field in ("start_time", "end_time"):
                            hour, minute = getattr(item, field).split(":")
                            setattr(item, field, f"{int(hour) + 2:02d}:{minute}")
                return result
        service = Service(barrier=Barrier(3))
        result = Planner(self.config, service).plan(service.plan.request)
        self.assertEqual(service.calls[-1]["data"]["previous_day"]["day_number"], 1)
        self.assertIn("overlap", service.calls[-1]["data"]["validation_feedback"])
        build_plan(result.itinerary, service.plan.request, "boundary-repair")

    def test_cached_responses_survive_a_worker_count_change(self):
        service = ConcurrentService(barrier=Barrier(3), fail={1})
        with self.assertRaises(AIServiceError):
            Planner(self.config, service).plan(service.plan.request, save_checkpoint=self.save)
        retry = ConcurrentService()
        Planner(replace(self.config, planner_workers=1), retry).plan(service.plan.request, checkpoint=self.saved)
        self.assertEqual(len(retry.calls), 1)

    def test_country_trip_still_requires_the_outlines_intercity_transfer(self):
        service = ConcurrentService(barrier=Barrier(3), broken_transfer=True)
        service.plan.request.destinations = ["Japan"]
        for entry in service.outline.days:
            entry.destinations = ["Japan"]
        for day in service.payload.days:
            day.destinations = ["Japan"]
            for item in day.schedule:
                if item.location:
                    item.location += ", Japan"
        Planner(self.config, service).plan(service.plan.request)
        self.assertIn("incoming transfer", service.calls[-1]["data"]["validation_feedback"])
        self.assertEqual(service.calls[-1]["data"]["day_to_generate"]["day_number"], 3)

    def test_outline_rejects_disconnected_boundaries(self):
        service = ConcurrentService()
        service.outline.days[1].start_location = "Kyoto"
        with self.assertRaisesRegex(AIServiceError, "start_location"):
            Planner(self.config, service).plan(service.plan.request)
        self.assertEqual(len(service.calls), 2)

    def test_route_feedback_collects_multiple_missing_connections(self):
        service = ConcurrentService()
        day = service.payload.days[0].model_copy(deep=True)
        day.schedule = [item for item in day.schedule if item.kind != "travel"]
        with self.assertRaises(ValueError) as raised:
            validate_day_prefix([day], service.plan.request)
        self.assertGreaterEqual(str(raised.exception).count("Add a transfer"), 3)

    def test_same_hotel_alias_connects_across_days_but_different_hotel_does_not(self):
        service = ConcurrentService()
        days = deepcopy(service.payload.days[:2])
        days[0].schedule.append(_transfer(days[0].schedule[-1].place_name, "Assumed Tokyo hotel", "19:00", "19:30", 0))
        days[1].schedule.insert(0, _transfer("Tokyo hotel (assumed)", days[1].schedule[0].place_name, "08:30", "09:00", 0))
        validate_day_prefix(days, service.plan.request)
        days[1].schedule[0].travel.origin = "Assumed Osaka hotel"
        with self.assertRaisesRegex(ValueError, "Assumed Tokyo hotel.*Assumed Osaka hotel"):
            validate_day_prefix(days, service.plan.request)

    def test_failure_stops_new_submissions_and_drains_running_calls(self):
        observed_failure = Event()
        class Service(ConcurrentService):
            def parse(inner, **kwargs):
                number = kwargs["data"].get("day_to_generate", {}).get("day_number")
                if number == 2:
                    if not observed_failure.wait(timeout=3):
                        raise AssertionError("Failure was not surfaced while another call was active")
                return super(Service, inner).parse(**kwargs)
        service = Service(fail={1})
        with self.assertRaises(AIServiceError):
            Planner(replace(self.config, planner_workers=2), service).plan(
                service.plan.request, save_checkpoint=self.save,
                progress=lambda message: observed_failure.set() if "could not complete" in message else None,
            )
        self.assertEqual([call["data"].get("day_to_generate", {}).get("day_number") for call in service.calls], [None, 1, 2])
        self.assertIn("2", self.saved["ready_days"])


class ReasoningTests(unittest.TestCase):
    def test_default_effort_and_worker_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            config = Config.load(Path(folder) / "missing")
        self.assertEqual((config.reasoning_effort, config.planner_workers), ("low", 3))

    def test_reasoning_and_workers_read_from_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "OPENAI_REASONING_EFFORT": "default", "TRIP_PLANNER_WORKERS": "2"
        }, clear=True):
            config = Config.load(Path(folder) / "missing")
        self.assertEqual((config.reasoning_effort, config.planner_workers), (None, 2))
        for setting, value in [("OPENAI_REASONING_EFFORT", "invalid"), ("TRIP_PLANNER_WORKERS", "0"),
                               ("TRIP_PLANNER_WORKERS", "5"), ("TRIP_PLANNER_WORKERS", "1.5")]:
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as folder:
                with patch.dict(os.environ, {setting: value}, clear=True), self.assertRaises(ConfigurationError):
                    Config.load(Path(folder) / "missing")

    def test_low_effort_is_sent_and_default_omits_it(self):
        for effort in ("low", None):
            requests = []
            result = DayResult(day=None, clarification_question="Add a day?")
            with sdk_client(stream_events(text=result.model_dump_json()), requests) as client:
                service = OpenAIService(replace(CONFIG, reasoning_effort=effort), client)
                service.parse(role="planner", prompt="test", data={}, response_model=DayResult)
                self.assertEqual(service.last_metadata.reasoning_effort, effort)
            if effort:
                self.assertEqual(requests[0]["reasoning"], {"effort": "low"})
            else:
                self.assertNotIn("reasoning", requests[0])

    def test_real_sdk_metadata_is_thread_local_and_client_initializes_once(self):
        barrier = Barrier(3)
        def handle(request):
            body = json.loads(request.content)
            number = json.loads(body["input"][1]["content"])["number"]
            result = DayResult(day=None, clarification_question=str(number))
            events = stream_events(text=result.model_dump_json())
            events[-1]["response"]["usage"] = {"input_tokens": number, "output_tokens": number,
                                              "total_tokens": number * 2,
                                              "output_tokens_details": {"reasoning_tokens": number}}
            content = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)
        with OpenAI(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
            service = OpenAIService(CONFIG)
            def parse(number):
                service.parse(role="planner", prompt="test", data={"number": number}, response_model=DayResult)
                barrier.wait(timeout=3)
                return service.last_metadata.usage.reasoning_tokens
            with patch("trip_planner.openai_service.OpenAI", return_value=client) as create:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    self.assertEqual(list(pool.map(parse, [1, 2, 3])), [1, 2, 3])
                create.assert_called_once()
            self.assertIsNone(service.last_metadata)


if __name__ == "__main__":
    unittest.main()
