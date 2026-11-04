# Technical documentation

This application keeps interaction in the terminal and renders a standalone browser document. Python owns collection state, validation, persistence and action dispatch. Two separately prompted AI responsibilities interpret language and produce itinerary candidates. The implementation is synchronous because each step depends on the previous one.

## Execution path

`python -m trip_planner` enters `cli.main()`. The CLI loads configuration explicitly and creates an `Application`, `Store`, `Interpreter` and `Planner`. Importing the package has no API side effects. Help, rendering and the offline demo do not construct an API client.

`Application` accepts explicit interpreter/planner objects plus input, output, renderer and browser functions. Tests substitute these directly; there is no interface hierarchy or dependency container. `OpenAIService` creates its SDK client only when a live operation is requested.

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

All contracts reject unexpected fields. `models.py` is the source of truth; generated JSON Schemas live in `schemas/`.

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

## Development and verification

Install development dependencies with `python -m pip install -e '.[dev]'`, then run `python -m pytest -q`. Tests use explicit interpreter/planner doubles and mocked SDK responses; they require no API key or network access. Run `python -m trip_planner demo --no-open` for an end-to-end offline JSON-to-page example. Rendering the supplied `examples/plan.json` also makes no API calls.

`tests/test_renderer.py` checks escaped narrative fields, Unicode, embedded offline CSS, responsive/print rules, unknown/free/over-budget states, file-URI browser opening and preservation of an existing page on failed atomic replacement. Other test modules cover conversation behavior, requests, schedules, arithmetic, storage and SDK failure handling.

Validation checks and the offline demo do not establish live API or real travel accuracy. A live credentialed smoke test is separate. Browser visual inspection was unavailable in this environment because the browser policy denied the local file URL; responsive/print verification is static. Final command results and any additional verification are recorded in the implementation report.

For routine changes, edit the focused module listed in the README, update its contract/schema if necessary, and run the relevant observable tests. Avoid adding a service layer, background worker or framework unless a new requirement needs it.
