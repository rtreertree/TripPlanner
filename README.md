# Local Trip Planner

Describe a trip in the terminal, open a readable itinerary in your browser, then refine it through chat. Drafts, plans and revisions stay in a local folder so you can leave, return and undo changes.

The browser page is an offline itinerary. Make changes in the terminal and refresh the page afterward.

## Install and run

Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Try the complete example without credentials or network access:

```sh
python -m trip_planner demo --no-open
```

The command prints absolute paths to the saved JSON and HTML. Open `itinerary.html` in a browser; its styles are included in the file. Omit `--no-open` to open the browser automatically. Print from the browser to save a PDF.

For your own trip, create a local `.env` using `.env.example` if you do not already have one. Preserve any existing credentials. Set:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-structured-output-model
TRIP_PLANNER_TIMEZONE=Asia/Bangkok
```

Choose a model available to your account that supports the **Responses API and Structured Outputs**. There is no hardcoded model default. Set `OPENAI_EXTRACTOR_MODEL` and/or `OPENAI_PLANNER_MODEL` to override `OPENAI_MODEL` independently for interpretation and planning. Environment variables take precedence over `.env`. The configured IANA timezone resolves phrases such as “next Friday”; it defaults to UTC.

```sh
python -m trip_planner
```

No saved work means the application starts the five prompts immediately. Otherwise, choose **Start a new trip** or a saved **Draft**/**Plan** from one numbered list; a partial trip name also works. New trips preserve existing trips.

## Describe → view → refine

The prompts appear one at a time:

```text
Trip name (optional): Japan Food and Culture
Days: three days
Destinations: Tokyo first, then Kyoto
Budget (optional): 75,000 yen for the whole trip
Preferences / special requests (optional): Traveling alone. Local food, quiet
places, temples and photography. Include Fushimi Inari and prefer trains.
```

Press Enter or type `skip` for an optional answer. Use `back` to replace the previous answer, `help` for examples, and `exit` to save a draft. Required answers cannot be skipped. Supply details under any label; the interpreter reads all five answers together. Follow-up questions resolve meaningful ambiguities, such as a budget with no currency or a per-person budget with no traveler count.

Defaults are one traveler, a balanced pace, numbered days without invented dates, and no spending limit. Estimates use the destinations' shared local currency (for example, JPY for Tokyo and Kyoto). If destinations use different currencies, estimates use **THB** (for example, Tokyo and Seoul). An explicitly supplied budget or reporting currency takes precedence; an ambiguous stated budget still needs clarification. Existing plans retain their reporting currency unless you request a change. Currency conversions are estimates with disclosed exchange-rate assumptions. This version supports **1–21 days**. A stated budget covers the whole group across the whole trip; an explicitly per-person budget is converted after traveler count is known. Changing traveler count alone preserves the existing group budget.

The app summarizes your request, creates the itinerary, saves it, and prints its HTML path. Then use terminal chat:

```text
You: Make Day 2 more relaxed.
You: Add Fushimi Inari to Day 3.
You: Why did you choose this neighborhood?
You: Actually, make it four days and add another traveler.
You: Undo my last change.
You: Exit
```

Clear edits are applied directly and saved as revisions. Questions and hypothetical suggestions leave the plan unchanged. A conflicting edit asks for one decision; answer naturally or type `Cancel` to keep the saved plan. Undo restores the prior itinerary as a new revision.

Local actions include `Help`, `Show my plan`, `Open the infographic`, `List my saved trips`, `Start a new trip`, `Continue my Japan trip`, `Undo my last change`, and `Exit`. These basic actions work without an API request. Starting or resuming a saved plan does not regenerate it.

If an API operation fails, choose `Retry` or `Exit`; an edit also permits `Cancel`. Accepted answers and pending operations are preserved. After a restart, an interrupted API operation waits for your explicit retry. If JSON was saved but the page failed to render, retry rendering without replanning. Save failures are reported as unsaved work.

## Optional commands

```sh
# Both AI roles, starting with a labeled answer file; continues into chat.
python -m trip_planner generate --text-file examples/trip_answers.txt --no-open

# Resume a plan created by the application.
python -m trip_planner chat --plan output/TRIP_ID/plan.json --no-open

# Rebuild HTML from saved JSON without an API call.
python -m trip_planner render --plan output/TRIP_ID/plan.json --no-open

# Render the supplied example without credentials.
python -m trip_planner render --plan examples/plan.json --no-open

python -m trip_planner --help
```

Use `--output-dir PATH` or `TRIP_PLANNER_OUTPUT_DIR` to change the default `output` folder. `TRIP_ID` above stands for the application-created folder printed when a plan is saved; ordinary startup does not require it.

## Files, data and privacy

Each trip has its own safe, generated identifier:

```text
output/<trip-id>/
  session.json        # draft answers, prompt position, pending operation, history
  conversation.json   # readable conversation messages
  request.json        # normalized request for the committed plan
  plan.json           # authoritative saved itinerary
  itinerary.html      # generated standalone view
  revisions/0001.json # previous and current plan revisions
```

Writes use temporary files and atomic replacement. `plan.json` is the committed plan; a failed generation or invalid candidate cannot replace it. Keep the whole trip directory to retain history and resume progress. Output and `.env` are ignored by version control.

Trip answers, preferences and conversations are stored locally without encryption. Real interpretation and planning send relevant trip data to OpenAI, including the active plan and a bounded recent conversation for chat. Credentials are read from configuration and excluded from saved plans and HTML. The SDK requests use `store=False`. Do not commit private output or share a rendered itinerary containing information you want to keep private.

The Pydantic models in `trip_planner/models.py` define the data contracts. `schemas/` contains exported JSON Schemas for interpreter results, normalized requests and saved plans. See `examples/trip_answers.txt`, `examples/conversation.txt`, `examples/request.json`, `examples/plan.json` and `examples/itinerary.html` for clearly labeled examples.

## Architecture and changes

The workflow is deliberately synchronous and small:

```text
labeled answers → interpreter → validated request → planner
               → domain checks + Python totals → saved JSON → HTML → chat
```

The interpreter and planner use separate prompts, typed contracts and Responses API calls. Python decides readiness, dispatches a fixed set of actions, validates candidates, assigns IDs/revisions, calculates costs and handles storage. A question never invokes the planner.

| Change | Location |
| --- | --- |
| Prompt sequence, chat routing and recovery | `trip_planner/conversation.py` |
| Interpreter, planning and revision instructions | `trip_planner/prompts/` |
| API request handling and metadata | `trip_planner/openai_service.py` |
| Typed contracts | `trip_planner/models.py` |
| Defaults, duration limit, schedule/transfer checks and cost arithmetic | `trip_planner/validation.py` |
| Local storage and atomic writes | `trip_planner/storage.py` |
| HTML and visual styling | `trip_planner/templates/itinerary.html.j2`, `trip_planner/static/styles.css` |
| Environment configuration and commands | `trip_planner/config.py`, `trip_planner/cli.py` |

The remaining state tracking is necessary to resume collection, clarify edits, retry failures and keep previous revisions. There is no server, database, account system or browser chat backend. [Technical documentation](docs/TECHNICAL.md) explains the contracts, state transitions and commit boundaries.

Direct runtime dependencies are the official `openai` SDK for API calls, `pydantic` for typed parsing/schemas, `Jinja2` for escaped HTML templates, and `python-dotenv` for optional local configuration. `pytest` and `build` are development dependencies. Supported dependency ranges are declared in `pyproject.toml`; templates, prompts and CSS are included in the installed package.

`requirements-dev.lock` records the exact tested dependency versions. To reproduce that environment, install it first with `python -m pip install -r requirements-dev.lock`, then install this package with `python -m pip install -e . --no-deps`.

## Verification and limits

```sh
python -m pytest -q
python -m trip_planner demo --no-open
python -m trip_planner render --plan examples/plan.json --no-open
```

Tests run without API credentials or paid requests, using deterministic interpreter/planner responses and mocked SDK results. They cover the guided journey, clarification, revision/recovery/persistence, request and itinerary validation, API failures, and escaped standalone HTML with responsive and print styles. The example is explicit demo data, never a fallback for failed real generation.

All prices, travel durations, opening hours and availability are estimates. The default budget includes accommodation, meals, activities, local transport and intercity transfers; travel from home to the first destination and back from the last is excluded unless requested. Unknown expenses are shown as unknown, totals become partial, and budget status becomes uncertain. Over-budget estimates remain viewable with warnings.

There are no live maps, bookings, weather, timetables or price checks. Local validation checks structure, time consistency, transfer connections, coverage and arithmetic; geographic feasibility and quality still depend on the model and your review. Undated itineraries use a representative date for timezone arithmetic and disclose that seasonal clock changes need checking. The app supports a single local user and assumes one process writes a trip at a time. Review important travel details before making reservations.
