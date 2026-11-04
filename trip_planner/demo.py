"""Explicit offline fixture. Real generation never falls back to this data."""

from .models import Cost, DayPayload, GenerationMetadata, ItineraryPayload, RequestDraft, ScheduleItem, Travel
from .validation import build_plan, normalize_request


def _item(kind, title, start, end, amount=0, place=None, location=None, travel=None, description=""):
    start_minutes = int(start[:2]) * 60 + int(start[3:])
    end_minutes = int(end[:2]) * 60 + int(end[3:])
    category = "transport" if kind == "travel" else "food" if kind == "meal" else "activities"
    return ScheduleItem(
        kind=kind, title=title, description=description or title,
        start_time=start, end_time=end, start_timezone="Asia/Tokyo", end_timezone="Asia/Tokyo",
        start_day_offset=0, end_day_offset=0, duration_minutes=end_minutes - start_minutes,
        place_name=place, location=location, travel=travel,
        cost=Cost(category=category, amount=amount, currency="JPY", label=title),
        notes=["Illustrative estimate; confirm current hours, fares, and accessibility."],
    )


def _transfer(origin, destination, start, end, amount, mode="train"):
    duration = (int(end[:2]) * 60 + int(end[3:])) - (int(start[:2]) * 60 + int(start[3:]))
    return _item("travel", f"{origin} → {destination}", start, end, amount,
                 travel=Travel(origin=origin, destination=destination, transport_mode=mode,
                               duration_minutes=duration, route_notes="Allow time to find platforms and buy tickets; times are estimates."))


def _city_day(number, city, morning, afternoon, lunch, dinner, title, summary):
    return DayPayload(
        day_number=number, date=None, title=title, summary=summary, destinations=[city],
        schedule=[
            _item("activity", morning, "09:00", "11:00", 500, morning, f"{morning}, {city}",
                  description="A slower morning exploring local culture and taking photographs, suited to the trip's interests."),
            _transfer(morning, lunch, "11:00", "11:30", 220, "walk / local train"),
            _item("meal", lunch, "11:30", "12:30", 1500, lunch, f"{lunch}, {city}",
                  description="A casual neighborhood lunch featuring local food; choose a restaurant on arrival."),
            _item("rest", "Tea and a quiet pause", "12:30", "13:00", 500),
            _transfer(lunch, afternoon, "13:00", "13:30", 220),
            _item("activity", afternoon, "13:30", "15:30", 1000, afternoon, f"{afternoon}, {city}",
                  description="Explore at a balanced pace, with time for photos and nearby streets rather than rushing between sights."),
            _item("free_time", "Flexible neighborhood time", "15:30", "17:00", 0),
            _transfer(afternoon, dinner, "17:00", "17:30", 220),
            _item("meal", dinner, "17:30", "19:00", 2500, dinner, f"{dinner}, {city}",
                  description="An informal dinner in a local food district. No reservation or availability is implied."),
        ],
        additional_costs=[Cost(category="accommodation", amount=11000, currency="JPY", label="One night in a modest hotel, one traveler")],
        notes=["Hotel location is assumed central; adjust transfers when accommodation is known.", "Breakfast is assumed included in accommodation."],
    )


def demo_plan():
    request = normalize_request(RequestDraft(
        trip_name="Japan · food, temples & quiet corners", destinations=["Tokyo, Japan", "Kyoto, Japan"],
        duration_days=3, budget=75000, currency="JPY", travelers=1, travelers_explicit=True,
        preferences="Local food, temples, photography, quiet places. Include Fushimi Inari, prefer trains, avoid nightlife.",
    ))
    first = _city_day(1, "Tokyo", "Sensō-ji, Asakusa", "Ueno Park", "Asakusa lunch district", "Ueno dinner district",
                      "Old Tokyo, at your own pace", "Temple streets, a neighborhood lunch, and green space for an unhurried first day.")
    second = _city_day(2, "Tokyo", "Meiji Jingū", "Nezu Museum garden", "Omotesandō lunch district", "Aoyama dinner district",
                       "Shrines, gardens & neighborhood food", "A leafy shrine and a garden-focused afternoon, linked by practical local transfers.")
    third = DayPayload(
        day_number=3, date=None, title="On to Kyoto's vermilion paths",
        summary="The intercity journey uses the morning, followed by a manageable afternoon around Fushimi Inari.",
        destinations=["Tokyo", "Kyoto"], schedule=[
            _transfer("Tokyo", "Kyoto", "08:00", "10:30", 14500, "Shinkansen (estimated service window)"),
            _item("rest", "Station arrival buffer", "10:30", "11:00", 0),
            _item("meal", "Kyoto Station lunch", "11:00", "12:00", 1500, "Kyoto Station", "Kyoto Station, Kyoto"),
            _transfer("Kyoto Station", "Fushimi Inari Taisha", "12:00", "12:30", 200, "JR local train and walk"),
            _item("activity", "Fushimi Inari Taisha", "12:30", "15:00", 0, "Fushimi Inari Taisha", "Fushimi ward, Kyoto",
                  description="Walk the lower torii paths for photography and temple atmosphere. The full summit hike is optional; surfaces and steps may limit accessibility."),
            _item("rest", "Tea near the shrine", "15:00", "16:00", 600),
            _transfer("Fushimi Inari Taisha", "Kyoto Station dinner", "16:00", "16:30", 200),
            _item("meal", "Kyoto Station dinner", "16:30", "18:00", 2500, "Kyoto Station dinner", "Kyoto Station, Kyoto"),
        ], additional_costs=[Cost(category="accommodation", amount=11000, currency="JPY", label="Final night in Kyoto")],
        notes=["The final night is included; onward travel home is outside this estimate.", "Do not treat the train window as a verified departure. Check timetables and reserve seats if needed."],
    )
    return build_plan(
        ItineraryPayload(summary="Three days of local food, temples, and quieter corners in Tokyo and Kyoto, with a realistic transfer morning.",
                         days=[first, second, third],
                         assumptions=["DEMO: illustrative offline data, not a live travel recommendation.",
                                      "One traveler, balanced pace, central modest hotels, and no calendar dates.",
                                      "Costs, availability, travel durations, and opening hours are estimates; check time-sensitive details before travel."],
                         warnings=["Two cities in three days leaves limited time in Kyoto. Add a day if you prefer a slower visit."]),
        request, "demo-japan", generation=GenerationMetadata(provider="offline fixture", demo=True),
    )
