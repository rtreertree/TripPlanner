# Build a Python Trip Planner

You are the implementation agent for this project. Build a working, maintainable application from the requirements below. Implement and verify the project; do not stop at a proposal, scaffold, or pseudocode.

## 1. Product goal

Create a simple Python console application that collects trip details through sequential labeled prompts such as `Trip name:` and `Days:`. Users answer each prompt in their own words. An OpenAI-powered interpreter converts those answers into structured trip data. A separate OpenAI-powered planning role receives the validated structured data and generates the itinerary. Save each itinerary as validated JSON, display it as an attractive local HTML infographic, and then let the user revise it through free-form terminal chat.

The core workflow is:

```text
Sequential prompts: Trip name -> Days -> Destinations -> Budget -> Preferences
    -> Collect the user's natural-language answers
    -> AI 1: convert the labeled answers into structured trip data
    -> Validate data and ask conversational follow-up questions if needed
    -> AI 2: generate an itinerary from the validated structured request
    -> Schema and itinerary validation
    -> Saved JSON plan
    -> Browser infographic
    -> Natural-language questions and revisions through AI 1
    -> AI 2 revises the itinerary when needed
    -> Updated JSON and infographic
```

Keep the first version focused on a single user running the application locally. The terminal is the interaction surface; the browser page displays the plan. A hosted service, database, account system, browser chat backend, or JavaScript framework is unnecessary for this version.

The interpreter and planner are two distinct AI responsibilities with separate prompts, typed response contracts, and API calls. They may use the same underlying model or independently configured models. Python code validates and routes the handoff between them; do not combine extraction and planning into one undifferentiated call.

### User journey

The user should always know what to do next, whether their work is saved, and where to make changes. Keep the experience to three stages: describe the trip, view the plan, and refine it. The table below defines the normal flow; later sections specify its data and implementation rules.

| Stage | User experience |
| --- | --- |
| Start | On first use, go directly to the five prompts when configuration is ready. If saved work exists, show one numbered list with “Start a new trip” followed by saved trips. Label each as “Draft” or “Plan,” with its name, destination summary when known, and last-updated time. Accept a number or name; ask which one only if the name matches multiple trips. |
| Describe | Ask the five prompts one at a time, marking optional ones. Explain skips and `Back` once. Then ask only follow-ups that materially affect the plan, one at a time, preserving everything already supplied. |
| Generate | Briefly summarize destinations, duration, travelers, budget scope, and relevant defaults, then say “Creating your itinerary…” and proceed. Do not require routine approval or expose AI-role handoffs to the user. |
| View | Save the plan, open the infographic unless `--no-open` is set, and show a short terminal summary: destinations, days, estimated total, and any budget or feasibility concerns. State that the plan is saved and that changes are made in the terminal. |
| Refine | Show a `You:` prompt with two examples, such as “Make Day 2 more relaxed” and “What can you do?” Apply clear edits directly, summarize their effects, and remind the user to refresh the browser. Questions leave the plan unchanged. |
| Leave and return | Save progress after each accepted answer and successful change. Confirm saved status on exit only when persistence succeeded. Continuing a draft returns to the next unanswered prompt or pending clarification; continuing a plan shows its summary, opens the saved page unless `--no-open` is set, and enters chat without regenerating it. |

Avoid extra onboarding, separate review screens, or confirmations for ordinary edits. Ask the user to choose only when missing information or a meaningful tradeoff prevents proceeding. Starting a new trip must preserve existing drafts and plans. At a clarification or error, end with one clear next action or a small set of choices. Do not repeat the help examples after every message.

## 2. Working approach

- Inspect the existing repository and applicable `AGENTS.md` instructions first. Preserve useful existing work.
- Make reasonable implementation decisions, document assumptions, and proceed without asking about routine choices.
- Complete the core workflow before adding optional features.
- Keep conversation interpretation, planning, domain validation, persistence, and rendering separate.
- Check current official documentation before implementing the OpenAI integration. Use a configurable model that supports the chosen structured output approach; do not assume a particular model name will remain available.
- Deliver working code, examples, documentation, and meaningful tests. Report any verification blocked by missing credentials or network access accurately.

### Simplicity and maintainability requirements

The implementation must be easy for a Python developer to read, debug, and change. Choose the simplest design that satisfies the requirements, including validation, recovery, and revision history. Treat maintainability as an acceptance criterion throughout implementation.

- Use straightforward Python, descriptive names, explicit control flow, and small functions with clear responsibilities. Split a function when it mixes responsibilities or becomes hard to follow; avoid arbitrary line-count limits and excessive one-line helpers.
- Keep the main workflow easy to trace: collect answers, interpret, validate, plan, validate the candidate, save, render, and chat. Make the distinction between the interpreter and planner visible in the code.
- Prefer plain functions, Pydantic models, and a few focused modules. Use classes only where they make state or a real integration boundary easier to manage. The suggested package layout is guidance; do not create empty modules or extra layers just to match it.
- Avoid speculative abstractions, deep inheritance, generic workflow engines, plugin registries, dependency-injection frameworks, and multi-agent frameworks. Do not build infrastructure for hypothetical future providers, users, or deployment environments.
- Keep the interpreter and planner easy to substitute in tests through simple explicit dependencies, such as passed objects or callables. A large interface hierarchy or dependency container is unnecessary.
- Prefer a synchronous implementation for this sequential local application unless a concrete requirement justifies concurrency. Avoid background workers, event buses, and asynchronous orchestration without a demonstrated need.
- Use the standard library where it fits, and keep third-party dependencies limited to clear needs. Document the purpose of each direct runtime dependency. Optional console libraries should earn their installation and maintenance cost.
- Keep business rules, cost calculations, configuration defaults, and storage conventions in clear authoritative locations. Reuse those rules across generation and revision instead of duplicating them. Do not hide a short, readable operation behind a generic abstraction merely to remove a few repeated lines.
- Handle expected failures at clear boundaries with specific exceptions and useful messages. Avoid broad catch-and-ignore blocks, silent fallbacks, hidden mutable global state, and import-time side effects.
- Write comments and docstrings that explain assumptions, contracts, or non-obvious decisions. Keep prompts and HTML templates readable and separate from workflow logic. Remove dead code, unused dependencies, and abandoned scaffolding before delivery.
- Test observable behavior and important failure paths using simple fixtures and test doubles. Avoid tests coupled to private implementation details or elaborate test frameworks beyond what the project needs.

Before delivery, review the code for unnecessary layers, duplicated rules, confusing names, and hard-to-follow control flow. Simplify where possible while preserving the required behavior. Include a short architecture overview in the README showing where to change prompts, validation rules, storage, and page styling, and explain any complexity that remains necessary.

## 3. Guided prompts and AI extraction

For a new trip, ask one labeled question at a time and wait for its answer before displaying the next prompt. Use this order:

1. `Trip name:` — optional.
2. `Days:` — required.
3. `Destinations:` — required; one or more places.
4. `Budget:` — optional; users may include the currency and whether it is per person or for the group.
5. `Preferences / special requests:` — optional free text.

Start with one short instruction: “Tell me about your trip. Press Enter or type ‘skip’ for optional questions. Type ‘back’ to change the previous answer, or ‘help’ for examples. You can change the plan afterward.” Clearly mark optional prompts. Re-ask an unanswered required question with a brief example, such as “How many days? For example, ‘five days’.” Users never need to enter JSON, Python lists, enum values, or internal field names. Accept natural answers such as “a week”, “Tokyo then Kyoto”, “around 150,000 yen”, or “I like quiet places and local food.”

During the five prompts, `Back` shows the previous prompt and its current answer. Accept a replacement, then return to the next unanswered prompt without discarding other answers. At the first prompt, explain that there is no earlier answer and stay there. During clarification, accept corrections in natural language and revalidate the draft; do not require restarting the five prompts. If information supplied earlier already answers a follow-up, use it instead of asking again.

Example terminal session:

```text
Trip name (optional): Japan Food and Culture
Days: five days
Destinations: Tokyo first, then Kyoto
Budget (optional): 150,000 yen for the whole trip
Preferences / special requests (optional): I'm traveling alone. I love local food,
temples, and photography. Include Fushimi Inari, prefer trains, and skip nightlife.

Assistant: I'll plan five days in Tokyo followed by Kyoto for one traveler,
           with a total budget of 150,000 JPY and a balanced pace.
           Creating your itinerary…

[After generation, show the estimated total and any warnings.]
Assistant: Your plan is saved, and the itinerary is open in your browser.
           Make changes here, then refresh the page to see them.
           Try “Make Day 2 more relaxed” or “What can you do?”
You: Actually, make it six days and add another person.
Assistant: I'll update it to six days for two travelers and keep the
           150,000 JPY budget as the group total.
[After saving the revision, summarize the changes and revised estimated total.]
```

The prompt sequence is controlled by Python; an AI call is not needed simply to display each label. Collect the five raw answers first, preserving which prompt each answer belongs to, then send them together to AI 1 for structured extraction. Do not rely solely on regex or direct casts to interpret natural-language answers.

If extraction reveals an ambiguity or invalid value, ask one concise natural-language follow-up at a time, merge the answer into the draft through AI 1, and validate again. Explain why the answer matters when it is not obvious, and offer concrete choices where helpful: “Does 500 mean USD or another currency?” Keep previously supplied details and corrections; do not restart the questionnaire or re-ask resolved questions. If an answer supplies information for several fields, retain all relevant details rather than discarding them because they appeared under another label. Later explicit corrections take precedence. Distinguish assumptions from explicit choices and avoid guessing required values.

Complete the five prompts, including skips for optional fields, before planning. Additional fields such as dates, traveler count, or pace can be extracted from any answer or given documented defaults; ask extra questions only when needed to resolve a material ambiguity. Do not send an incomplete or ambiguous request to the planner. Once collection and validation are complete, proceed without a routine confirmation step.

Keep defaults lightweight: an omitted budget means no spending limit, omitted dates mean numbered days, and omitted traveler count and pace mean one traveler and a balanced pace. Disclose relevant defaults in the pre-generation summary rather than asking the user to approve each one. Do not ask for hotels, meal choices, or transport details unless the user's constraints make them necessary. `Help`, `Back`, and `Exit` are local collection actions and must not be saved as trip answers. Help returns to the same prompt; exiting preserves the draft.

The internal normalized request must contain the following fields. The user-facing prompts map to this contract; users do not enter these internal field names themselves.

| Field | Required | Behavior |
| --- | --- | --- |
| `trip_name` | No | Human-readable title; derive a sensible title if omitted. |
| `destinations` | Yes | One or more nonempty destination strings extracted from the answers. Preserve the requested visit order unless the user asks to optimize it. A broad region is acceptable when the user delegates the choice of places to the planner; record that delegation. |
| `duration_days` | Yes | Positive integer representing the total trip length, including travel between destinations. |
| `budget` | No | Positive amount for the entire traveling group across the entire trip. Omitted or `null` means no spending limit. |
| `currency` | No | Reporting currency code extracted from the answers. If a stated budget has an ambiguous currency, ask before planning. With no budget or currency supplied, default to `USD` and disclose that assumption. |
| `preferences` | No | Free text covering interests, must-visit places, food, accessibility, preferred transport, exclusions, and other constraints. Default to an empty string. |
| `start_date` | No | ISO date. When omitted, use Day 1, Day 2, etc., without inventing calendar dates. |
| `travelers` | No | Positive integer; default to 1. All plan costs must use this group size. |
| `pace` | No | `relaxed`, `balanced`, or `packed`; default to `balanced`. |

For example, AI 1 converts the labeled answers above into this internal request; the user never has to write it:

```json
{
  "trip_name": "Japan Food and Culture",
  "destinations": ["Tokyo, Japan", "Kyoto, Japan"],
  "duration_days": 5,
  "budget": 150000,
  "currency": "JPY",
  "preferences": "Local food, temples, and photography. Include Fushimi Inari. Prefer trains and avoid nightlife.",
  "start_date": null,
  "travelers": 1,
  "pace": "balanced"
}
```

Validate extracted values locally, then explain problems conversationally rather than displaying schema errors. Trim whitespace and deduplicate repeated destinations without losing their order. Handle Unicode names correctly. Resolve relative dates using the user's configured timezone and the current local date; ask when the intended date is ambiguous. Document any practical trip-length limit rather than silently truncating requests.

If a destination is too ambiguous or the request contains an important contradiction, ask a concise clarifying question. Missing optional fields alone must not prevent generation. Clarify material ambiguities such as nights versus days or a date range that conflicts with the stated duration. Treat an unqualified budget as the group total and state that in the summary. For an explicitly per-person budget, ask for traveler count if it was not supplied, then convert to the group total; do not silently use the one-traveler default in this case. When travelers change later, preserve the current group budget unless the user also asks to change it, and mention this in the change summary.

Define a typed interpreter result containing at least:

- `intent`: create a trip, edit a trip, ask a question, list or resume trips, show or open a plan, undo, cancel a pending edit, request help, or exit.
- `request_draft`: partial trip fields that can remain unknown during collection. Use a separate partial model rather than forcing missing values into a complete request.
- `request_updates`: explicitly requested changes to trip constraints when editing an existing plan.
- `change_instructions`: the user's requested itinerary changes, where applicable.
- `trip_reference`: a reference to an existing trip when relevant; the application resolves it against locally stored trips.
- `missing_required_fields`, `clarification_question`, and `assumptions`.
- `assistant_message`: a short conversational response.

The application decides readiness from collection state and validated data rather than trusting a model-generated flag. Track which prompts were answered or explicitly skipped, and keep the raw answers, draft, and current prompt available across follow-up questions and restarts. The planner receives the complete validated request and relevant normalized instructions, rather than being responsible for extracting facts from the raw answers. A question or local action should not trigger itinerary generation.

## 4. Generated itinerary

Generate exactly `duration_days` days, numbered consecutively from 1. Every day must include:

- A short title, summary, and the destination or destinations covered.
- A chronological schedule with explicit time slots.
- Places to visit, their locations, useful descriptions, and a reason each fits the trip.
- Travel segments between successive places and between destinations, with transport method and estimated travel duration.
- Meals, rest time, and realistic transition buffers appropriate to the requested pace.
- Estimated costs and practical notes, such as reservations or accessibility considerations when relevant.

Group nearby activities geographically and avoid unnecessary backtracking. Intercity transfers must consume actual trip time; do not schedule a full sightseeing day on top of a long transfer. If the requested destinations cannot realistically fit, explain the conflict instead of silently omitting destinations or inventing instantaneous travel.

When a request cannot fit, ask one actionable question with a small number of alternatives, such as “Would you prefer to add a day or remove Kyoto?” Keep the current draft or saved plan until the user chooses. A valid plan with an estimated budget overage may still be saved and displayed, with the overage clearly stated and one or two suggested changes; do not trap the user in repeated automatic replanning.

Treat prices, travel durations, availability, and opening hours as estimates unless supported by a real data source. The core version does not need live maps, weather, booking, or search integrations. Do not invent live verification, exact train departures, bookings, citations, or guaranteed availability. Show relevant assumptions and recommend checking time-sensitive details.

By default, the budget includes accommodation estimates, meals, activities, local transport, and transfers between requested destinations. Travel from the user's home to the first destination and home from the last destination is excluded unless explicitly requested. State this scope in the plan. When origin or accommodation details are missing, use clearly labeled assumptions rather than pretending they were supplied.

## 5. JSON contract and domain validation

Use typed Pydantic models as the source of truth and export the corresponding JSON Schema. The saved JSON is the authoritative plan; the HTML must be rendered from it.

At minimum, define these entities and fields:

### Saved plan

- `schema_version`: version of the file format.
- `trip_id`: application-generated identifier, stable across revisions.
- `revision`: application-generated positive integer, starting at 1.
- `created_at`, `updated_at`: application-generated UTC timestamps.
- `request`: the normalized trip request extracted from conversation and used for this revision.
- `summary`: concise overview and highlights.
- `days`: ordered list of day objects.
- `budget_summary`: budget scope, category totals, estimated total, budget limit, remaining amount, currency, and budget status.
- `assumptions`, `warnings`: lists of human-readable statements.
- `generation`: provider, model when applicable, generation time, and available token usage metadata. Mark demo data explicitly.

### Day

- `day_number`, `date` (nullable), `title`, `summary`, `destinations`.
- `schedule`: ordered list of schedule items.
- `additional_costs`: itemized day costs not represented by schedule items, such as accommodation.
- `estimated_total_cost`, `notes`.

### Schedule item

- `id`: stable identifier retained when the item survives a revision.
- `kind`: `activity`, `meal`, `travel`, `rest`, or `free_time`.
- `title`, `description`.
- `start_time`, `end_time`: local 24-hour times, with explicit timezone information and day offsets wherever a transfer crosses midnight or timezones.
- `duration_minutes`.
- `place_name`, `location`: meaningful for a visit; nullable where not applicable.
- `travel`: nullable object containing origin, destination, transport mode, estimated duration, and directions or route notes. Required for travel items.
- `cost`: category, estimated amount or `null` when unknown, and reporting currency. Costs apply to the entire group.
- `notes`: practical information and uncertainty where relevant.

Use explicit cost categories such as accommodation, food, transport, activities, and other. Each expense must appear once, either on a schedule item or in `additional_costs`. A cost of zero means free; an unknown cost is `null` and must never be treated as free.

Separate the model's itinerary payload from the persisted envelope as needed. IDs, timestamps, revisions, and arithmetic totals are owned by the application, not trusted to the language model.

Implement deterministic checks beyond JSON shape:

1. Day count and numbering match the request, and all requested destinations are represented or explicitly reported as infeasible.
2. Each day contains a usable schedule; item times are ordered, durations are consistent, and items do not overlap when timezone and day offsets are considered.
3. Travel segments connect consecutive visits, with sufficient scheduled transfer time.
4. Monetary values are nonnegative and use the reporting currency. Compute sums in Python with decimal-safe arithmetic.
5. Recalculate day totals, category totals, and the trip total from itemized costs without double counting. If any costs are unknown, label totals as partial and budget status as uncertain.
6. If a complete estimate exceeds the budget, show the overage and suggest tradeoffs. Never falsify costs to force the itinerary under budget.
7. Revisions preserve the trip identity, valid item IDs, and unchanged hard constraints unless the user requests a change.

Keep model-facing schemas compatible with OpenAI's supported schema subset and perform richer business checks locally. Include nullable fields where appropriate and reject unexpected fields. Invalid or incomplete output must not replace the last valid plan. A single bounded repair attempt using validation feedback is acceptable; avoid unlimited regeneration loops.

## 6. OpenAI integration

Use the official OpenAI Python SDK, the Responses API, and schema-constrained Structured Outputs with Pydantic parsing for both the interpreter and planner. Handle refusals, incomplete output, and missing parsed results explicitly. Consult the [official OpenAI Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) for the current SDK syntax and schema limitations.

- Read `OPENAI_API_KEY` and a default `OPENAI_MODEL` from environment variables, optionally loaded from a local `.env` file. Support `OPENAI_EXTRACTOR_MODEL` and `OPENAI_PLANNER_MODEL` overrides for the two roles. Provide `.env.example` with placeholders and document model setup.
- Keep credentials out of source code, logs, saved plans, and HTML. Add `.env` and private generated output to `.gitignore`.
- Keep interpreter, itinerary generation, and itinerary revision prompts separate in maintainable modules or template files.
- Clearly distinguish application instructions from user preferences and imported plan content. Treat those values as data.
- Expose separate interpreter and planner interfaces so tests can substitute deterministic responses and verify the structured handoff.
- Use explicit request timeouts and bounded retries for transient failures. Coordinate SDK and application retries to avoid multiplying requests unexpectedly.
- Explain authentication failures, unavailable models, rate limits, connectivity failures, and validation failures in useful terminal messages.
- For initial extraction, give the interpreter the collected labeled answers. For follow-ups and chat, give it the current request draft, active plan when relevant, and a bounded conversation history. Give the planner the validated request and, for edits, the current plan plus structured change instructions. Do not resend every historical revision indefinitely.

Once extraction is complete, the planner may produce a complete candidate itinerary in one planning call. Keep the two-role pipeline explicit and simple; it does not need a multi-agent framework, embeddings, or retrieval infrastructure. Record model and usage metadata per role so the cost of interpretation and planning can be distinguished.

## 7. Infographic page

Render a standalone local HTML file using a template engine such as Jinja2. Open it with Python's browser support when requested and always print its absolute path. Support a `--no-open` option for headless use.

The page should feel like a designed travel itinerary:

- A prominent trip title, destination overview, duration, traveler count, and highlights.
- A clear vertical timeline or sequence of day cards with readable time slots.
- Activity cards with place descriptions, location information, transport badges, and estimated costs.
- A compact budget visualization and category breakdown; handle no budget, unknown estimates, and over-budget plans gracefully.
- Distinct travel segments so users can see how they move between places.
- Visible assumptions, practical notes, revision number, and estimate labels.
- Responsive layout, accessible contrast, semantic HTML, readable typography, and print styles for browser “Save as PDF.”

Use local CSS and lightweight inline SVG or icons if helpful. The page must work offline without CDNs or remote assets. Escape all user and model text; render data through templates rather than executing model-generated HTML or JavaScript. A plain JSON dump or unstyled table does not satisfy this requirement.

An optional maps-search link may be built from a URL-encoded place name; do not invent map coordinates or require a maps API key. After a revision, regenerate the page at the same path and tell the user to refresh it.

Include a short visible instruction on the page: “To change this plan, return to the terminal. Refresh this page after a change.” The page is a readable itinerary, without nonfunctional edit buttons or chat controls. If opening the browser fails, print the saved HTML path and continue the terminal session.

## 8. Conversational changes

Use the guided prompts above for initial trip creation, then switch to free-form terminal chat to answer questions, perform local actions, and revise the active plan. Later edits do not require repeating all five prompts. Users can resume a trip conversationally, for example “Continue my Japan Food and Culture trip.” Resolve ambiguous trip names by asking which saved trip they mean.

Example requests:

- “Add Fushimi Inari to Day 4.”
- “Replace the museum on Day 2 with a food market.”
- “Make Day 3 less tiring.”
- “Use trains instead of taxis where practical.”
- “Reduce the budget to 120,000 JPY.”
- “Why did you choose this neighborhood?”

Route messages through the interpreter to distinguish itinerary edits, questions, clarifications, and local actions. A question should receive an answer without creating a revision. An ambiguous or infeasible edit should produce a clarification or explanation without corrupting the plan.

For an edit, AI 1 extracts the requested constraint updates and itinerary changes. Validate them, then send the current plan and validated changes to AI 2 to generate a complete candidate itinerary or an equally safe typed update. Preserve unaffected days where practical; update related travel segments, times, and costs when a change affects them. Do not implement arbitrary model-generated code execution or blindly apply unvalidated JSON patches.

Validate the candidate, save a new revision, update the infographic, and summarize what changed, including any budget impact. Keep previous revisions and let the user say “Undo my last change” to restore the previous plan as a new revision. Do not silently change destinations, trip length, dates, or budget to accommodate an unrelated request.

Keep change summaries short and specific: what changed, any effect on other days or transport, and the new estimated total or budget difference. If the user asks a question such as “Would another day help?”, answer it before making changes; a hypothetical question is not permission to edit. When a requested edit requires relaxing another explicit constraint, explain the tradeoff and ask which constraint to change. Keep that edit pending so a short reply such as “Add a day” completes the same request. Let the user say `Cancel` to discard a pending edit and return to the saved plan. A question during clarification should be answered without discarding the pending edit. If there is no previous revision to restore, say so and leave the plan unchanged.

Support natural-language actions such as “What can you do?”, “Show my plan”, “Open the infographic”, “List my saved trips”, “Start a new trip”, and “Exit.” Help should show a few examples of edits, questions, resume, and undo, rather than a long command reference. “Show my plan” gives a concise terminal summary; “Open the infographic” opens the saved page. Listing trips uses the same selection list as startup. Starting or switching trips saves the current work first. The model may identify an intent, but Python must dispatch only a fixed set of allowed operations and resolve files from application-owned trip IDs. Save conversation history locally, without credentials, so the session can be resumed. Normal chat edits can be applied directly because history and undo are available.

## 9. CLI and local storage

The normal entry point follows the user journey in Section 1. CLI arguments are optional developer or automation utilities, never a prerequisite for normal use. Selecting a saved trip must not require a file path, trip ID, or exact title.

```bash
# Start the guided trip prompts, then enter free-form revision chat.
python -m trip_planner

# Optional utility: process saved labeled answers through both AI roles.
python -m trip_planner generate --text-file examples/trip_answers.txt

# Resume a saved trip.
python -m trip_planner chat --plan output/<trip-id>/plan.json

# Render an existing plan without making an API request.
python -m trip_planner render --plan output/<trip-id>/plan.json --no-open

# Demonstrate the infographic without an API key or network access.
python -m trip_planner demo --no-open
```

Persist unfinished collection sessions, including the current prompt, raw answers, skipped fields, and extracted drafts, so users can continue after a restart. Store each trip in its own directory containing the extracted normalized request, `plan.json`, `itinerary.html`, revision history, and conversation history. Use application-controlled IDs and safe filenames rather than raw destination text as filesystem paths. Write JSON atomically and preserve the last valid revision on extraction, generation, or validation failure. Report rendering or file-permission errors clearly and keep the saved JSON recoverable.

Handle Ctrl+C and EOF cleanly. Importing the package, running help, rendering an existing plan, and running the offline demo must not require API credentials or cause an API call. Do not silently substitute demo data when real generation fails.

### Recovery without starting over

- Before collecting a new trip, check local configuration for the API key and a configured model for each role, using the default model or role overrides. If configuration is missing, explain the setup step and the offline demo option. Do not make a paid API call just to check setup or block access to saved plans.
- During interpretation, generation, or revision, display a short progress message. On failure after bounded retries, explain what failed and offer `Retry` or `Exit`; for an edit, also offer `Cancel` to return to the saved plan. Keep the answers or pending edit so retry does not require retyping. Never report an unsaved change as successful. One progress message per operation is sufficient; a progress bar or live activity feed is unnecessary.
- If JSON was saved but rendering failed, say “Your plan is saved, but the page could not be created.” Let the user retry rendering without calling the planner again. If saving itself failed, explain that the latest work is not yet saved and allow a save retry before claiming success.
- Recognize basic local choices such as help, back during collection, exit, retry, canceling a pending edit, saved-trip selection, and showing or opening an existing plan without an API call. Natural-language variants may use the interpreter. Users must be able to leave or access saved work during a network outage.
- After a restart, restore saved answers and drafts. Resume at the interrupted step; do not automatically repeat an unfinished paid generation or edit. Offer to retry it. If a save failed, recover only the last successfully persisted state and explain the limitation.

## 10. Suggested implementation

Prefer a small Python package with typed functions and focused modules:

```text
trip_planner/
  __init__.py
  __main__.py
  cli.py
  config.py
  models.py
  conversation.py
  interpreter.py
  planner.py
  openai_service.py
  validation.py
  storage.py
  renderer.py
  prompts/
  templates/itinerary.html.j2
  static/styles.css
examples/
tests/
pyproject.toml
.env.example
.gitignore
README.md
```

Python 3.11+, the official OpenAI SDK, Pydantic, Jinja2, and pytest are suitable foundations. Use Typer and Rich if they improve the console experience without complicating installation. Include templates and assets in the installed package. Document dependency versions and a reproducible installation path.

## 11. Verification and acceptance criteria

Use mocked OpenAI responses and realistic fixtures for automated tests. The default test suite must run without credentials, network access, or paid API calls.

Cover the important behavior:

- Sequential prompts appearing in the specified order, one at a time; optional skips, re-prompting for missing required answers, going back to replace an answer without losing other answers, and resuming an unfinished collection session.
- First use starting directly with prompts; returning users choosing a draft or plan from one list by number or name; starting a new trip preserving existing work; resuming a plan opening its saved page and chat without regeneration, while respecting `--no-open`.
- AI extraction from labeled natural-language answers such as “a week” or “Tokyo then Kyoto”, including details supplied under another label, corrections, missing optional fields, Unicode, and invalid duration or budget.
- Follow-up questions for missing destination or duration, ambiguous currency, per-person budgets without an explicit traveler count, and conflicting dates. Assert that planning is not called while required information remains unresolved and that resolved details are not asked again. Verify that an unqualified budget is summarized as a group total and remains unchanged when traveler count alone changes.
- The two-role handoff: extraction receives all collected labeled answers, the planner receives the validated structured request, and planning does not begin before the prompt sequence and necessary clarifications are complete. Extraction alone never creates an itinerary or revision.
- A valid generated itinerary passing through parsing, domain validation, JSON persistence, and HTML rendering.
- Incorrect day counts, overlapping time slots, missing transfers, inconsistent totals, unknown costs, and budget overages.
- A targeted chat edit preserving unaffected content while recalculating affected travel and costs.
- Natural-language questions and local actions leaving the revision unchanged; conversational undo, saved-trip selection, draft persistence, and restart/resume behavior.
- A hypothetical question leaving the plan unchanged; a conflicting edit asking for one concrete decision and accepting a short follow-up answer or cancellation; an over-budget estimate remaining viewable with clear tradeoffs.
- Refused, incomplete, malformed, and failed API responses preserving the previous valid plan.
- Retrying a failed operation without re-entering answers, canceling a failed edit without changing the saved plan, rendering recovery without replanning, truthful save-failure messages, and basic local actions working without network access.
- HTML escaping and a successful offline render and CLI demo.

Run an end-to-end offline demo and inspect the generated page at desktop and narrow widths when browser tooling is available. Verify that the itinerary is readable and printable and that no remote resources are required. An actual OpenAI smoke test is optional when credentials and network access are available; never claim to have run one if it was not run.

The project is complete when a user can follow the describe → view → refine journey with their own API key, leave and resume their work, and undo a change without needing to understand the internal AI roles or file formats. The offline example must demonstrate rendering independently of OpenAI availability.

## 12. Deliverables

1. Working application implementing the core workflow.
2. README with setup, environment configuration, model selection instructions for both AI roles, the sequential prompt flow, sample follow-ups and revision chats, the extraction-to-planning handoff, internal data formats, optional CLI utilities, storage layout, and limitations of estimated travel information.
3. Example labeled natural-language answers and follow-up conversations, their extracted request JSON, a complete valid sample plan, and its rendered infographic. Clearly label fixtures and demo content.
4. Exported JSON Schemas for interpreter results, normalized requests, and plans, plus automated tests for the critical behaviors above.
5. A final implementation report with commands run, test results, example output paths, and any remaining limitations.

Per-day locking, packing checklists, additional languages, live reload, and live travel integrations are outside the first version. Add them only in a later explicitly requested iteration. A complete, understandable start-to-resume flow is the priority.
