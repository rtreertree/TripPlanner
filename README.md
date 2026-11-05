# Local Trip Planner

Describe a trip in the terminal, open a standalone itinerary in your browser, then refine it through chat. Drafts, plans and revisions stay in a local folder so you can return later and undo changes.

## Install and run

Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Try the complete offline demo without credentials or network access:

```sh
python -m trip_planner demo --no-open
```

The command prints absolute paths to the saved JSON and HTML. Open `itinerary.html` in a browser, or omit `--no-open` to open it automatically. Print from the browser to save a PDF.

For your own trip, copy `.env.example` to `.env` if you do not already have one. Preserve existing credentials and set:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-structured-output-model
TRIP_PLANNER_TIMEZONE=Asia/Bangkok
```

Choose a model available to your account that supports the Responses API and Structured Outputs. There is no hardcoded model default. Optional `OPENAI_EXTRACTOR_MODEL` and `OPENAI_PLANNER_MODEL` settings override the shared model independently. Environment variables take precedence over `.env`.

```sh
python -m trip_planner
```

## Describe, view and refine

Answer five prompts: trip name, days, destinations, budget, and preferences. Days and destinations are required; press Enter or type `skip` for optional answers. Use `back` to replace an answer, `help` for examples, or `exit` to save a draft.

The app clarifies ambiguities, creates and saves your itinerary, then enters terminal chat:

```text
Make Day 2 more relaxed.
Add Fushimi Inari to Day 3.
Why did you choose this neighborhood?
Undo my last change.
Exit
```

Refresh the browser page after an edit. On later launches, select a saved draft or plan by number or partial name. Local actions include `Show my plan`, `Open the infographic`, `List my saved trips`, and `Start a new trip`.

Planning creates a short route outline, then generates up to three days concurrently using low reasoning effort. Each concurrent job checks its schedule and can repair it once; responses are saved as they arrive, including days that finish out of order. The app then validates connections in day order, repairs an affected boundary when needed, and saves the complete itinerary. If a request times out, type `Retry` to continue using the saved responses. After restarting, select the saved draft or plan and type `Retry`. Edits reuse unaffected days when the trip constraints are unchanged.

`OPENAI_REASONING_EFFORT=low` is the default; use `default` to omit reasoning settings for models that do not support them. `TRIP_PLANNER_WORKERS=3` controls concurrent day requests (1–4); set it to `1` for sequential generation. Both settings can be changed in `.env`.

`OPENAI_TIMEOUT_SECONDS` controls how long a request may go without receiving data (default 90 seconds). Responses stream while generating, so an active response can take longer. `OPENAI_REQUEST_DEADLINE_SECONDS` limits an active step (default 300, checked between events), and `OPENAI_MAX_RETRIES` controls SDK retries before a stream opens (default 0). These settings are read from `.env`; see [DOC.md](DOC.md) for output limits and recovery details.

Trips support 1–21 days. Defaults are one traveler, a balanced pace and no spending limit. Estimates use the destinations' shared local currency, or THB when destinations use different currencies; an explicit budget/reporting currency takes precedence. Budgets cover the whole group across the whole trip.

## Files and documentation

`main` contains this README, [DOC.md](DOC.md), the application package, timeout/recovery regression tests, and the configuration needed to install and run it. Prompts, the HTML template, CSS and the offline demo are included in the package. The [`secondary` branch](https://github.com/rtreertree/TripPlanner/tree/secondary) preserves the original repository, including its tests, examples, exported schemas, development lockfile and source documents.

See [DOC.md](DOC.md) for configuration, optional commands, answer-file examples, storage, architecture, recovery and limitations. `trip_planner/models.py` defines the data contracts; JSON Schemas can be generated directly from those models.

Trips are saved under `output/<trip-id>/` by default. Use `--output-dir PATH` or `TRIP_PLANNER_OUTPUT_DIR` to change it. `.env` and generated output are ignored by version control. Local trip files are unencrypted, and live planning sends relevant trip data to OpenAI.

Travel prices, durations, opening hours and availability are estimates. Review details before making reservations. The app has no live booking, routing, weather or price integrations.
