# Application documentation

## Repository layout

`main` contains the runnable application and two documentation files: `README.md` for quick setup and this file for the complete operating and technical reference. The original repository is preserved on `secondary` at commit `273245ed84bbf8c64d169fd17c3f824bbe50ffe1`, including the original agent brief, implementation report, technical notes, tests, examples, schemas and development lockfile.

```text
README.md
DOC.md
pyproject.toml
.env.example
.gitignore
trip_planner/
  __main__.py             # module entry point
  cli.py                 # commands and answer-file loading
  config.py              # environment and .env configuration
  conversation.py        # guided prompts, chat and recovery
  interpreter.py         # language interpretation
  planner.py             # itinerary generation and revision
  openai_service.py      # API boundary and errors
  models.py              # typed data contracts
  validation.py          # request, schedule and cost validation
  storage.py             # local sessions and atomic persistence
  renderer.py            # standalone HTML rendering
  demo.py                # deterministic offline itinerary
  prompts/               # runtime interpretation/planning instructions
  templates/             # packaged HTML template
  static/                # packaged CSS
```

Python 3.11+ and the runtime dependencies declared in `pyproject.toml` are required: `openai`, `pydantic`, `Jinja2` and `python-dotenv`. Installing the package includes all prompts, templates and styles; separate example or schema files are unnecessary at runtime. The `trip-planner` command is equivalent to `python -m trip_planner` after installation.

## Configuration

Configuration is loaded explicitly from the current directory's `.env`, then overridden by existing environment variables. Use `.env.example` as a starting point and preserve any existing credentials.

| Setting | Purpose / default |
| --- | --- |
| `OPENAI_API_KEY` | Required for live interpretation and planning. |
| `OPENAI_MODEL` | Shared model; no hardcoded default. Choose an available model supporting Responses Structured Outputs. |
| `OPENAI_EXTRACTOR_MODEL` | Optional interpreter override, otherwise `OPENAI_MODEL`. |
| `OPENAI_PLANNER_MODEL` | Optional planner override, otherwise `OPENAI_MODEL`. |
| `TRIP_PLANNER_TIMEZONE` | IANA timezone used to resolve phrases such as “next Friday”; default `UTC`. |
| `TRIP_PLANNER_OUTPUT_DIR` | Saved-trip folder; default `output`. `--output-dir` overrides it. |

Both roles need a configured model for new trips. Help, the demo and rendering work without API credentials. Saved plans can be viewed and local actions used during an outage; live questions and edits require configuration and connectivity.

## Guided workflow and defaults

On first use, the app starts five prompts in order: trip name, days, destinations, budget and preferences. On later launches, choose a saved Draft or Plan by number or partial name, or start a new trip. New trips preserve existing work.

```text
Trip name (optional): Japan Food and Culture
Days: three days
Destinations: Tokyo first, then Kyoto
Budget (optional): 75,000 yen for the whole trip
Preferences / special requests (optional): Traveling alone. Local food,
quiet places, temples and photography. Include Fushimi Inari; prefer trains.
```

Press Enter or type `skip` for optional answers. Required answers cannot be skipped. `back` replaces the previous answer, `help` shows examples, and `exit` saves a draft. Details supplied under any label are interpreted together. Follow-up questions resolve material ambiguities, such as an unspecified budget currency or a per-person budget without a traveler count.

Defaults are one traveler, a balanced pace, numbered days without invented dates, and no spending limit. Trips support 1–21 days. Estimates use the destinations' shared local currency (JPY for Tokyo and Kyoto), or THB for destinations using different currencies (Tokyo and Seoul). An explicit budget/reporting currency takes precedence; ambiguous stated budgets still need clarification. Existing plans preserve their reporting currency unless a change is requested. Conversion rates are estimates and must be disclosed.

A stated budget covers the whole group across the whole trip. An explicitly per-person budget is converted once traveler count is known. Changing traveler count alone preserves the existing group budget.

After planning, the app saves JSON and HTML, prints the HTML path, and enters terminal chat. Clear edits create revisions. Questions and hypothetical suggestions leave the itinerary unchanged. A conflicting edit asks for one decision; answer naturally or type `Cancel`. `Undo my last change` restores the prior itinerary as a new revision. Refresh the browser after a successful edit.

Local actions include `Help`, `Show my plan`, `Open the infographic`, `List my saved trips`, `Start a new trip`, `Continue my Japan trip`, `Undo my last change`, and `Exit`. Basic local actions make no API request. Resuming a saved plan does not regenerate it.

## Optional commands and answer files

```sh
# Generate a deterministic example without credentials or network access.
python -m trip_planner demo --no-open

# Generate from your own labeled answer file, then enter chat.
python -m trip_planner generate --text-file answers.txt --no-open

# Resume an application-created plan.
python -m trip_planner chat --plan output/TRIP_ID/plan.json --no-open

# Rebuild HTML from a saved plan without an API call.
python -m trip_planner render --plan output/TRIP_ID/plan.json --no-open

python -m trip_planner --help
```

`TRIP_ID` stands for the generated folder printed after saving; normal startup does not require it. `--no-open` prints the file path without opening a browser. The page contains its own styles and needs no server. Browser printing can save a PDF.

For `generate`, create `answers.txt` with these labels:

```text
Trip name: Japan Food and Culture
Days: three days
Destinations: Tokyo then Kyoto
Budget: 75000 yen for the group
Preferences / special requests: One traveler, local food and temples.
  Include Fushimi Inari and prefer trains.
```

`Days:` and `Destinations:` lines are required. The other labels are optional, and indented continuation lines remain part of the preceding answer. Python reads labels; the interpreter extracts their meaning.

## Saved files and privacy

```text
output/<trip-id>/
  session.json        # draft answers, prompt position, pending work, history
  conversation.json   # readable conversation messages
  request.json        # normalized request for the committed plan
  plan.json           # authoritative saved itinerary
  itinerary.html      # derived standalone view
  revisions/0001.json # committed revision snapshots
```

Keep the whole trip directory to retain history and resume progress. `.env` and generated output are ignored by version control. Files are stored locally without encryption.

Live interpretation and planning send relevant trip data to OpenAI, including the active plan and bounded recent chat history. Credentials are read from configuration and excluded from saved plans and HTML. SDK requests use `store=False`. A rendered itinerary can still contain private trip details; review it before sharing.

## Architecture

This application keeps interaction in the terminal and renders a standalone browser document. Python owns collection state, validation, persistence and action dispatch. Two separately prompted AI responsibilities interpret language and produce itinerary candidates. The implementation is synchronous because each step depends on the previous one.

## Execution path

`python -m trip_planner` enters `cli.main()`. The CLI loads configuration explicitly and creates an `Application`, `Store`, `Interpreter` and `Planner`. Importing the package has no API side effects. Help, rendering and the offline demo do not construct an API client.

`Application` accepts explicit interpreter/planner objects plus input, output, renderer and browser functions. These dependencies can be substituted directly for verification; there is no interface hierarchy or dependency container. `OpenAIService` creates its SDK client only when a live operation is requested.

The normal flow is:

1. Select existing work, or validate local configuration and create a draft.
2. Collect all five labeled answers, saving after each accepted answer or skip.
3. Send the collected answers and draft to the interpreter.
4. Merge extracted fields and corrections, clarify material unknowns, then call `normalize_request()`.
5. Send the complete normalized request and any edit instructions to the planner.
6. Validate its typed candidate and compute authoritative totals in `build_plan()`.
7. Commit JSON, save session state, render HTML, and enter chat.

A follow-up answer returns through the interpreter. A question returns an answer without generation. Local actions dispatch through a fixed allowlist and do not execute model-generated commands, code or file paths.

## Contracts and ownership

All contracts reject unexpected fields. `trip_planner/models.py` is the source of truth. Each Pydantic model exposes `model_json_schema()` when a JSON Schema export is needed; runtime parsing does not require checked-in schema files.

| Contract | Purpose and owner |
| --- | --- |
| `RequestDraft` | Partial extraction, with nullable fields and flags for explicit travelers, per-person budget and delegated destination selection. |
| `InterpreterResult` | Intent, draft, explicit request updates, itinerary instructions, trip reference, missing fields, clarification, assumptions and conversational reply. Nullable field clearing is explicit. |
| `TripRequest` | Complete normalized trip constraints accepted by Python before planning. |
| `PlannerResult` | A typed `ItineraryPayload`, or an actionable feasibility/clarification question. |
| `ItineraryPayload` / `DayPayload` | Planner-owned descriptions, schedules, itemized costs, assumptions and warnings; no trusted arithmetic or persisted envelope. |
| `SavedPlan` | Application-owned schema version, trip identity, revision, UTC timestamps, request, validated days, computed budget summary and generation metadata. |

Each schedule item has a kind, title, description, local start/end times, timezones, day offsets, duration, optional place/location, cost and notes. A travel item additionally requires origin, destination, mode, duration and route notes. Visits and meals need meaningful places and locations. Schedule IDs persist when a surviving item is identified; Python assigns IDs to new items.

`Cost.amount = 0` means free; `null` means unknown. Each expense belongs exactly once to a schedule item or a day's `additional_costs`. Additional costs can carry human-readable labels, such as an accommodation assumption.

`SavedPlan.generation` identifies demo content or the actual provider/model and generation time. Its role records separate interpreter/planner model usage where available. Metadata never contains API credentials.

## Validation and arithmetic

`normalize_request()` trims and deduplicates destinations without changing their order, derives an omitted title and applies documented defaults. It enforces 1–21 days, positive traveler counts and budgets, a three-letter reporting currency and required destinations/duration. A per-person budget requires an explicitly known traveler count before conversion. After conversion, edits operate on the group budget, so a traveler-count-only edit does not multiply it again.

The interpreter supplies `RequestDraft.destination_currencies` using the resolved places. Without a specified currency, normalization chooses the shared local currency, or THB when destinations use different currencies. Unknown local currencies require clarification rather than a silent USD fallback. A stated budget still requires its own unambiguous currency. Explicit currencies and existing saved-plan currencies are preserved. Planning instructions require estimated conversion rates to be disclosed; there is no live foreign-exchange integration.

The interpreter resolves linguistic ambiguities, explicit corrections and dates using the configured local date/timezone. Python does not trust an AI readiness flag: the prompt collection state, clarification result and normalized request govern the handoff. Prompts distinguish instructions from serialized user data.

`build_plan()` checks:

- Exact day count and consecutive numbering; dates match the request, and requested destinations are covered unless choosing places was delegated.
- Nonempty usable days with meals and rest/free time.
- Valid 24-hour local times, explicit IANA zones or UTC offsets, and nonnegative day offsets. Times convert to UTC for duration and overlap checks across days.
- Travel details and enough scheduled transfer time. Travel endpoints connect consecutive visits; intercity changes need explicit scheduled transfers.
- Nonnegative costs in the reporting currency, unique IDs and matching trip identity for revisions.

Undated trips use a representative date for timezone calculations and show a seasonal-clock-change assumption. This provides consistent arithmetic without inventing travel dates; it cannot verify future daylight-saving transitions.

All monetary sums use `Decimal(str(amount))`. JSON models carry numeric values and persist calculated totals as numbers. Python recomputes day totals, category totals, the group total and remaining budget from itemized costs. It does not accept model-supplied totals. Any unknown expense produces a partial total and `uncertain` budget status; an otherwise complete overage produces an explicit warning and suggested tradeoffs rather than an automatic regeneration loop.

`validate_plan()` checks persisted schema/revision/timestamps, item identity, itinerary rules and totals against the itemized data. Local coverage and route checks use conservative normalized name matching; they cannot establish real geographic distances, actual opening hours or booking availability.

## Conversation state and recovery

`Session` in `storage.py` stores the application-generated trip ID, timestamps, raw answers, explicitly skipped fields, prompt index, draft, stage, clarification, pending operation, conversation history and recent interpretation metadata.

| Stage | Next action |
| --- | --- |
| `collect` | Ask the next unanswered labeled prompt; `Back` replaces the previous answer while retaining later accepted answers. |
| `interpret` | Interpret collected answers or a saved chat message. |
| `clarify` | Ask one useful follow-up; retain the pending edit and current valid plan. |
| `generate` | Plan from the normalized pending request, then validate and commit. |
| `chat` | Accept a question, edit or local action for the committed plan. |

Pending data contains the message/instructions, validated request when ready, assumptions, and the base plan revision. This lets explicit Retry repeat the failed operation without retyping. A restart does not silently repeat an interrupted paid call. A committed plan newer than a pending operation's base revision supersedes that stale operation.

Questions during clarification preserve the pending edit. Cancel returns to the saved plan's constraints. Undo loads the previous committed revision and validates/saves its itinerary as a new revision, retaining the trip identity. Switching or creating a trip saves the current session first.

Failures have separate recovery boundaries:

- Interpretation or planning failures preserve accepted answers, pending instructions and the current plan.
- A locally invalid itinerary permits one planner repair call with validation feedback, then requires user action.
- A save failure retries persistence of the already validated candidate without another planner call. Exit reports that the latest work is unsaved.
- A render failure after commit leaves recoverable JSON. A render retry rebuilds the same HTML path without calling AI.
- A browser-open failure leaves the path available and the terminal session usable.
- Ctrl+C and EOF attempt to persist progress; saved status is reported only after success.

## Storage and commit boundaries

`Store` resolves trip paths from generated identifiers, validates the safe identifier format, rejects symbolic-link trip directories and verifies document identity against its containing folder. User destination text never becomes a filename. Imported trip references resolve against the saved-trip list.

Each JSON or HTML write uses a temporary file in the destination directory, flushes and syncs it, then calls `os.replace()`. Failed writes clean up temporary files and cannot truncate an existing destination. This is a local single-writer design; it has no locking or cross-process coordination.

A plan commit writes its revision snapshot and normalized request, then replaces `plan.json` last. **`plan.json` is the commit marker and authoritative saved plan.** Multiple files are not one filesystem transaction: interruption can leave an extra revision snapshot or a newer `request.json`. Resume follows `plan.json`, not an unreferenced history file. The HTML is a derived artifact and can always be rebuilt from the committed plan. Session/conversation writes occur separately, with reconciliation against the committed revision on resume.

Revisions start at 1. A trip ID and creation timestamp persist across successful changes; update timestamps use UTC. Previous snapshots remain available for undo. Drafts have session/conversation files before they have a plan.

## OpenAI boundary

`Interpreter.interpret()` receives all labeled raw answers, a partial draft, the current message, the active plan where relevant, pending instructions and at most 12 recent conversation messages. It also receives the configured local date/timezone. Initial collection itself makes no API requests.

`Planner.plan()` receives a complete `TripRequest`, the current plan for edits, normalized change instructions and optional validation feedback. Initial planning and revision use distinct prompt files plus shared planning rules. It never needs to extract facts from the original raw answer labels.

`OpenAIService.parse()` uses the official SDK's synchronous `responses.parse(..., text_format=PydanticModel, store=False)`. It checks refusals, completion status and the presence of a valid parsed result. Authentication, access, missing model, quota/rate limit, timeout, connectivity, bad request and invalid output failures become useful terminal messages; provider error bodies and environment contents are not displayed.

Client timeout defaults to 90 seconds and SDK transient retries to one. The application does not add another automatic network retry loop. A domain-invalid candidate may cause one explicit repair call; user-selected Retry is a separate decision. Separate model settings select interpretation and planning without hardcoding a model that may become unavailable.

## Rendering and security

`render_plan()` takes a validated `SavedPlan` and renders the package's Jinja template. HTML autoescaping applies to every user/model narrative, location, currency and metadata field. Only the trusted packaged CSS is marked as markup. No model HTML or JavaScript executes, and no external assets are needed.

The page includes day anchor navigation, semantic day/timeline sections, explicit group costs, unknown/partial labels, a compact category chart, assumptions, warnings, revision metadata and the terminal-change instruction. Responsive styles adapt narrow layouts; print rules support browser PDF output. Visual bars supplement the text values and are hidden from assistive technology. No browser edit or chat controls are shown.

HTML regenerates at the same path after a successful change. The application prints an absolute path even in headless mode. Credentials remain in environment/local `.env`, and private generated output is ignored by version control; the local trip files themselves are unencrypted.

## Verification and maintenance

The repository cleanup was verified on 5 November 2026. All 144 preserved offline tests passed against the reduced application's code. A wheel built from a clean copy of the reduced source was installed separately and passed help, console entry point, bundled-resource, demo, rendering, saved-plan chat and documented answer-file checks from outside the repository. No live API call was made.

Run a complete local smoke check without API credentials:

```sh
python -m trip_planner --help
python -m trip_planner demo --no-open
python -m trip_planner render --plan output/TRIP_ID/plan.json --no-open
```

Use the trip folder printed by the demo for `TRIP_ID`. The demo validates an itinerary, persists JSON and session state, and renders a standalone page. The render command rebuilds that page from committed JSON. These commands do not verify live API access or real travel accuracy.

The original 144-test offline suite and pinned development environment are preserved on `secondary`. In a separate checkout of that branch, install `requirements-dev.lock`, then install the package with `python -m pip install -e . --no-deps` and run `python -m pytest -q`. The suite uses deterministic interpreter/planner substitutes and mocked SDK responses, covering collection, clarification, revisions, undo, persistence, recovery, schedule/cost validation and escaped HTML. Original schema/example consistency checks apply to that branch's retained files.

For a source change on `main`, validate the affected behavior and verify installation with bundled prompts, the template and CSS from outside the repository. Update Pydantic models when contracts change; schema files can be regenerated from those models. Keep runtime assets inside the package.

## Limits

All prices, durations, opening hours and availability are estimates. There are no live maps, bookings, weather, timetables, exchange rates or price checks. The default budget includes accommodation, meals, activities, local transport and intercity transfers. Travel from home to the first destination and back from the last is excluded unless requested.

Unknown expenses are shown as unknown, totals become partial and budget status becomes uncertain. Over-budget estimates remain viewable with warnings and tradeoffs. Validation checks structure, timing, transfer connections, destination coverage and arithmetic; geographic feasibility and itinerary quality still depend on the model and user review.

Undated itineraries use a representative date for timezone arithmetic and disclose the need to check seasonal clock changes. The app supports a single local user and assumes one process writes a trip at a time. It has no server, database, account system or browser chat backend. Live generation requires valid credentials, model access and connectivity. Review important details before making reservations.
