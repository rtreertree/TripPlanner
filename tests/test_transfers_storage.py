"""Regression checks for airport transfer chains and non-trip output folders."""

from pathlib import Path
import tempfile
import unittest

from trip_planner.demo import _item, _transfer, demo_plan
from trip_planner.config import Config
from trip_planner.conversation import Application
from trip_planner.models import DayOutline, DayPayload, Travel, TripRequest
from trip_planner.storage import Session, Store
from trip_planner.validation import validate_day_outline, validate_independent_day


def flight_day():
    day = DayPayload(
        day_number=1, date=None, title="Fly to Chiang Mai", summary="A flight with airport transfers.",
        destinations=["Thailand"], additional_costs=[], notes=[], schedule=[
            _transfer("Bangkok hotel", "Suvarnabhumi Airport", "07:00", "08:00", 400, "Taxi"),
            _item("rest", "Check in and wait", "08:00", "10:30"),
            _transfer("Suvarnabhumi Airport", "Chiang Mai International Airport", "10:30", "11:45", 1500, "Flight"),
            _transfer("Chiang Mai International Airport", "Chiang Mai hotel", "11:45", "12:15", 200, "Taxi"),
            _item("meal", "Lunch", "12:15", "13:15", 100, "Chiang Mai hotel", "Chiang Mai, Thailand"),
            _item("rest", "Rest after travel", "13:15", "14:00"),
        ],
    )
    for item in day.schedule:
        item.start_timezone = item.end_timezone = "Asia/Bangkok"
        item.cost.currency = "THB"
    outline = DayOutline(day_number=1, title=day.title, destinations=["Thailand"], instructions="Fly north.",
                         reuse_existing=False, start_location="Bangkok", end_location="Chiang Mai",
                         overnight_base="Chiang Mai", incoming_transfer=Travel(
                             origin="Bangkok", destination="Chiang Mai", transport_mode="Flight",
                             duration_minutes=75, route_notes="Estimated flight time; airport transfers are additional.",
                         ))
    request = TripRequest(trip_name="Thailand", destinations=["Thailand"], duration_days=1, currency="THB")
    return day, outline, request


class TransferTests(unittest.TestCase):
    def test_city_journey_accepts_connected_airport_transfers(self):
        day, outline, request = flight_day()
        validate_independent_day(day, request, outline)

    def test_direct_city_transfer_still_works(self):
        day, outline, _ = flight_day()
        day.schedule = [_transfer("Bangkok", "Chiang Mai", "10:30", "11:45", 1500, "Flight")] + day.schedule[4:]
        validate_day_outline(day, outline)

    def test_disconnected_airports_are_rejected(self):
        day, outline, _ = flight_day()
        day.schedule[2].travel.origin = "Don Mueang Airport"
        with self.assertRaisesRegex(ValueError, "incoming transfer"):
            validate_day_outline(day, outline)

    def test_wrong_destination_is_rejected(self):
        day, outline, _ = flight_day()
        day.schedule[2].travel.destination = "Phuket Airport"
        with self.assertRaisesRegex(ValueError, "incoming transfer"):
            validate_day_outline(day, outline)

    def test_waiting_and_schedule_buffers_do_not_count_as_travel_time(self):
        day, outline, _ = flight_day()
        for item in day.schedule:
            if item.travel:
                item.travel.duration_minutes = 10
        with self.assertRaisesRegex(ValueError, "75 minutes of travel"):
            validate_day_outline(day, outline)

    def test_unrelated_intermediate_visit_breaks_the_chain(self):
        day, outline, _ = flight_day()
        day.schedule.insert(2, _item("meal", "Unrelated city visit", "08:30", "09:00", 0,
                                     "Restaurant in Bangkok", "Bangkok, Thailand"))
        with self.assertRaisesRegex(ValueError, "incoming transfer"):
            validate_day_outline(day, outline)


class TripDiscoveryTests(unittest.TestCase):
    def test_committed_recovery_supersedes_an_older_running_sessions_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            plan = demo_plan()
            store.save_plan(plan)
            stale = Session(trip_id=plan.trip_id, stage="generate", pending={"base_revision": 0})
            store.save_session(stale)
            app = Application(Config(), store, None, None, no_open=True,
                              read=lambda prompt: "Exit", write=lambda message: None)
            app.run(store.load_session(plan.trip_id))
            resumed = store.load_session(plan.trip_id)
            self.assertEqual(resumed.stage, "chat")
            self.assertEqual(resumed.pending, {})
            self.assertEqual(store.load_plan(plan.trip_id).revision, 1)

    def test_report_containers_and_unrelated_folders_are_not_trips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "empty").mkdir()
            reports = root / "live-api-check-test"
            reports.mkdir()
            (reports / "timing.json").write_text("{}")
            Store(reports).save_session(Session())
            store = Store(root)
            session = Session()
            store.save_session(session)
            store.save_plan(demo_plan())
            entries = store.list_trips()
            self.assertEqual({entry["trip_id"] for entry in entries}, {session.trip_id, "demo-japan"})
            self.assertEqual(store.warnings, [])

    def test_corrupt_real_trip_still_reports_a_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            damaged = root / "damaged"
            damaged.mkdir()
            (damaged / "session.json").write_text("broken")
            store = Store(root)
            self.assertEqual(store.list_trips(), [])
            self.assertEqual(len(store.warnings), 1)
            self.assertIn("damaged", store.warnings[0])


if __name__ == "__main__":
    unittest.main()
