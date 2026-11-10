# Local Trip Planner presentation outline

This is a slide-by-slide script for a mixed product and engineering audience. The 24 main slides support a roughly 35–45 minute technical walkthrough, including a short demo. Three appendix slides supply details for questions. Each slide has copy for the canvas, instructions for constructing the visual, and speaker notes with the explanation. Use the notes for depth and keep the canvas focused on the example or mechanism named in the title. Source references are optional verification pointers. All material needed to build the slides is included here.

**Presentation example.** A three-day Tokyo and Kyoto trip runs through the deck. The packaged offline fixture supplies the itinerary, exact budget figures and rendering demo. The sample clarification, model payloads, targeted edit and timeout show how the live path works. Those scenarios are illustrative and are separate from the fixture run.

| Slides | Presentation section |
| --- | --- |
| 01–06 | Traveler goals and use cases |
| 07–15 | Architecture, program flow, model roles and planning loop |
| 16–21 | Schedule validation, budgets, revisions, recovery and rendering |
| 22–24 | Offline demo, test evidence and system limits |
| 25–27 | Data contracts, API settings and operational reference |

## Part I · Traveler use cases

### Slide 01 · Local Trip Planner

**On-slide copy**

- **Local Trip Planner**
- A terminal assistant for planning, viewing and revising a trip
- One running example · Three days in Tokyo and Kyoto

**Visual.** Place the title and subtitle at left. At right show a simple two-stop route labeled **Tokyo · Days 1–2** and **Kyoto · Day 3**. Use a rail connector labeled **Intercity transfer**. The layout can be drawn directly from these labels. Geographic precision is unnecessary.

**Speaker notes.** A traveler enters natural-language answers, receives a scheduled itinerary with itemized group costs, then asks questions or revises the plan through terminal chat. The browser shows a locally generated itinerary. The technical story is how Python turns several model responses into a single, validated revision and preserves partial progress when generation fails.

### Slide 02 · The traveler’s workflow

**On-slide copy**

| Traveler goal | Input | Result |
| --- | --- | --- |
| Create a trip | “Three days, Tokyo then Kyoto, JPY 75,000 for the group” | Daily schedule, timed transfers and group estimate |
| Inspect a plan | “Show my plan” or “Open the infographic” | Terminal summary or browser itinerary |
| Ask about a choice | “Why did you put the train on Day 3?” | An explanation grounded in the active plan |
| Refine an itinerary | “Make Day 2 more relaxed” | A new saved revision if the candidate passes validation |
| Return later | Select a saved plan or draft | Continue chatting, collecting answers or recovering work |

**Visual.** Use the table as the main composition. Add a narrow line below it labeled **Terminal for input · Browser for reading · Local folder for continuity**.

**Speaker notes.** The intended user is an individual assembling a trip, potentially for a group. Their needs include honoring ordered destinations, leaving room for meals and rest, and seeing how travel changes the day and the budget. A plan can be printed from the browser to PDF. The application runs locally and uses a remote model for live language understanding and itinerary design. Local actions and offline viewing remain available independently of model generation.

**Code reference.** `trip_planner/cli.py`, `trip_planner/conversation.py`, `trip_planner/templates/itinerary.html.j2`.

### Slide 03 · Use case 1 · Describe a trip and resolve ambiguity

**On-slide copy**

- Five prompts cover trip name, days, destinations, budget and preferences.
- Days and destinations are required. Optional answers can be skipped.
- `back` revisits an answer. `help` gives examples. `exit` saves the draft for later.
- Example clarification · “Which currency should I use for the $1,000 budget?”

**Visual.** Build a terminal transcript with these five answers on the left. On the right show the follow-up question, the traveler’s reply **“USD, for the whole group”**, and the resolved fields **3 days · Tokyo then Kyoto · USD 1,000 group budget**.

```text
Trip name          Japan food and temples
Days               Three days
Destinations       Tokyo then Kyoto
Budget             $1,000 for the group
Preferences        Local food, quiet mornings and Fushimi Inari
```

**Speaker notes.** The questionnaire saves each accepted answer and the current position before moving on. It passes all labeled answers together to the interpreter, so a traveler can mention a must-visit or a correction in another field. The prompt instructs the interpreter to ask one actionable question when an ambiguity affects planning. The follow-up updates the same draft. If an omitted field has a safe default, such as pace, Python can supply it after the required details are ready. This USD example illustrates clarification. The separate offline fixture uses JPY.

**Code reference.** `Application.collect()`, `Application.interpret()`, `prompts/interpreter.txt`.

### Slide 04 · Use case 2 · Read and question an itinerary

**On-slide copy**

- The terminal summarizes the route, traveler count, estimate and revision.
- The browser shows the daily timeline, transfers, itemized costs and planning assumptions.
- “Why did you put the train on Day 3?” uses the active plan as context.
- A question returns a reply while the saved revision stays the same.

**Visual.** Create a mock itinerary crop using the offline Day 3 fixture. Show **08:00–10:30 Tokyo to Kyoto · estimated Shinkansen window**, **10:30–11:00 station arrival buffer**, **11:00–12:00 Kyoto Station lunch**, and **12:30–15:00 Fushimi Inari Taisha**. Use a terminal inset with the question and the illustrative reply **“The Tokyo days stay together, and taking the train in the morning leaves the afternoon for Fushimi Inari.”** Add an **Illustrative reply** label.

**Speaker notes.** Exact phrases such as `Show my plan` and `Open the infographic` run locally. An open-ended explanation normally invokes the interpreter, which sees the active itinerary and budget summary. Python handles the `question` intent by printing and saving the response in chat history. It skips itinerary planning and creates no revision. A question during clarification can leave the existing pending operation in place. The browser is a read-only document. Edits happen in the terminal, and the viewer refreshes to see the regenerated page.

**Code reference.** `Application.chat()`, `Application.interpret()`, `Application.dispatch()`, `Interpreter.interpret()`.

### Slide 05 · Use case 3 · Revise, cancel or undo

**On-slide copy**

| User action | Application outcome |
| --- | --- |
| “Make Day 2 more relaxed” | Validates a complete candidate and saves revision 2 |
| “Cancel” during a pending edit | Drops the pending edit and retains the committed plan |
| “Undo my last change” | Restores the previous snapshot as a new revision |

**Visual.** Draw **r1 · Original**, **r2 · Revised Day 2**, **r3 · Restored r1 content** along one line. Above it show a branch from r1 labeled **Uncommitted edit** looping back to r1 under **Cancel**. Below the revisions show Day 1 and Day 3 carried forward in the targeted-edit example.

**Speaker notes.** An itinerary-only instruction can change one day while preserving the trip-level request. The planner can reuse unaffected days when the outline marks them reusable and their schedules still validate. A change such as “make it four days” changes the normalized request and disables direct day reuse. Cancel applies before commit. Undo applies after commit, reads the immediately preceding numbered snapshot, and commits restored content with a new revision number. Undo is a local command and has no model call. Repeated undo follows the immediately preceding snapshot, which may be the edit that a prior undo restored away from.

**Code reference.** `Application.cancel()`, `Application.dispatch()`, `Planner.plan()`, `Store.previous_plan()`.

### Slide 06 · Use case 4 · Save, resume and recover

**On-slide copy**

- A draft stores accepted answers before an itinerary exists.
- A committed plan opens from local files. A saved draft resumes at its recorded stage.
- Interrupted model work waits for the traveler to type `Retry`.
- A failed edit leaves the last committed itinerary available.

**Visual.** Use two rows. In the first, **Incomplete questionnaire** leads to **Saved draft** and **Resume next unanswered prompt**. In the second, **Timed-out generation** leads to **Saved outline and completed days** and **Retry unfinished work**. Show the prior committed plan alongside the second row with the label **Still viewable during a failed edit**.

**Speaker notes.** On launch, the app lists saved work by last update time. The traveler can choose by number or an unambiguous partial name. If the saved stage is interpretation or generation, the app asks before repeating work. The useful distinction is between a draft, a generation checkpoint and a committed plan. The draft is the user’s input state. A checkpoint is internal work in progress. Only a committed plan can become the authoritative itinerary.

**Code reference.** `Application.select_trip()`, `Application.recover()`, `Application.run()`, `Store.list_trips()`.

## Part II · Program flow and agentic AI

### Slide 07 · Runtime architecture

**On-slide copy**

- **Local Python process** · CLI, conversation controller, planner and validators
- **OpenAI Responses API** · Typed interpretation, route and day proposals
- **Local trip folder** · Session, plan and revision history
- **Browser** · Standalone itinerary HTML

**Visual.** Draw a **Traveler** connected to **Terminal / Application**. Inside a boundary labeled **Local machine**, add **Interpreter**, **Planner**, **Validation**, **Store**, **Jinja renderer** and **Browser**. Both model roles connect through **OpenAIService** to **Responses API** outside the local boundary. Label the outgoing edge **System prompt + trip context as JSON** and the return edge **Parsed result**. Connect Store to a folder icon and show the renderer reading the committed plan and writing HTML for the browser.

**Speaker notes.** `python -m trip_planner` and the installed `trip-planner` command reach `cli.main()`. The CLI assembles a Store, Interpreter, Planner and Application for interactive work. The Application owns the state machine. The planner controls parallel day jobs and the order of validation. The SDK client for each service instance is created lazily. The application has no server, application database or browser backend. The browser opens a file URL. Dependencies include Python 3.11+, Pydantic for contracts, the OpenAI SDK with HTTPX for model calls, and Jinja2 for HTML.

**Code reference.** `pyproject.toml`, `trip_planner/cli.py`, `trip_planner/conversation.py`, `trip_planner/openai_service.py`, `trip_planner/renderer.py`.

### Slide 08 · Conversation state machine

**On-slide copy**

- `collect` saves raw answers. `interpret` extracts a draft or classifies a chat turn.
- `clarify` holds a question and pending context. The reply returns to `interpret`.
- `generate` produces a candidate. Successful commit enters `chat`.
- `chat` dispatches known local actions directly and routes free text to `interpret`.

**Visual.** Draw five labeled nodes. Connect **Collect → Interpret → Generate → Chat**. Add **Interpret → Clarify** for missing or ambiguous details, **Generate → Clarify** for feasibility issues, **Clarify → Interpret** for a reply, **Chat → Interpret** for free text, and **Interpret → Chat** for a question or applicable local action. Add a dashed recovery loop beside Interpret and Generate labeled **Retry same stage after failure**. Label the Generate-to-Chat edge **Validate, commit and render**.

**Speaker notes.** `Application.run()` drives the stages in a loop. A labeled answer file can start at `interpret` because Python has already read the labeled fields. Selecting an existing trip restores its session and loads its committed plan if present. Recovery is a prompt around the current stored stage. A model question response can return to the existing clarification context. A new trip starts a fresh `Session`. The fixed action list also recognizes phrases such as `Undo my last change`, and `Continue my Japan trip` is handled as local trip selection.

**Code reference.** `Application.run()`, `Application.chat()`, `Application.interpret()`, `Application.recover()`, `Session`.

### Slide 09 · End-to-end data flow

**On-slide copy**

| Step | Data passed forward |
| --- | --- |
| Collect and interpret | Labeled answers and chat context produce `InterpreterResult` |
| Normalize | `RequestDraft` becomes a complete `TripRequest` |
| Plan | `PlanningOutline` guides one `DayResult` per generated day |
| Assemble | Ordered `DayPayload` objects form an `ItineraryPayload` |
| Commit and render | Python constructs `SavedPlan`, commits JSON and renders HTML |

**Visual.** Build a left-to-right pipeline using the five rows. Put **Local state** under the collector, **Model** over interpretation and planning, and **Python validation** between proposals and the commit. Label the parallel branch **One missing day per job** and its join **Check in day order**. Draw an extra input from **Current plan** to the model stages for edits and questions.

**Speaker notes.** A normal first run passes the questionnaire answers through the interpreter once after collection, plus any clarification turns. The interpreter result can contain a partial draft. Python merges and normalizes it before planning. The outline is trip-wide while each generated day is narrow. The planner assembles the typed day payloads into a complete candidate with summary, assumptions and warnings. `build_plan()` assigns authoritative identity and computes totals. `plan.json` is the commit marker. HTML derives from that file and can be rebuilt independently.

**Worked trace for the diagram.** Use these values under the respective stages. This is an illustrative live request using the same constraints as the fixture.

| Stage | Selected values to show |
| --- | --- |
| Collected text | `Days: Three days`, `Destinations: Tokyo then Kyoto`, `Budget: JPY 75,000 for the group` |
| Interpreted draft | `duration_days=3`, `destinations=["Tokyo", "Kyoto"]`, `budget=75000`, `currency="JPY"`, `travelers=null`, `pace=null` |
| Normalized request | Same duration, route and group budget, plus `travelers=1`, `pace="balanced"` and `start_date=null` |
| Model candidates | Outline gives Day 3 an incoming Tokyo–Kyoto transfer. Day 3 proposes timed travel, lunch and a shrine visit. |
| Committed output | Revision 1 contains three validated days, assigned schedule item IDs and a budget summary derived from the itemized costs. |

**Code reference.** `trip_planner/models.py`, `Application.interpret()`, `Application.generate()`, `Application.commit()`.

### Slide 10 · How the system uses agentic AI

**On-slide copy**

| Model responsibility | Python responsibility |
| --- | --- |
| Interpret intent and ask for missing information | Route allowed actions and maintain session state |
| Propose a trip-wide route and divide it into days | Enforce request readiness and schedule rules |
| Generate schedules and revise candidates from feedback | Bound retries, save checkpoints and commit revisions |

**Visual.** Under the table draw **Propose → Validate** with one branch **Accept candidate** and one branch **Return validation feedback to model**. Add a separate **Ask traveler** branch for conflicting or infeasible constraints. Put a line around the model boxes labeled **Structured model calls** and a line around the decisions labeled **Python control flow**.

**Speaker notes.** The agentic behavior comes from goal decomposition, choosing route and schedule details, using validation feedback to repair a candidate, and asking the user to resolve a conflict. There are two prompted responsibilities, interpreter and planner. The planner uses separate outline and day prompts, with one day per worker job when generation is needed. The roles may use the same configured model or different models. Workers are concurrent calls coordinated by the application. The fixed program flow decides what can happen next. Model outputs have no tool, shell, browser or booking access, and the application alone can write files. The system feeds back domain errors as instructions for another structured attempt.

**Code reference.** `trip_planner/interpreter.py`, `trip_planner/planner.py`, `trip_planner/openai_service.py`, `prompts/planning_rules.txt`.

### Slide 11 · The interpreter’s context and output

**On-slide copy**

- **Inputs** · All labeled answers, partial draft, current message, up to 12 recent messages and local date/timezone.
- **During chat** · Active plan request, itinerary and budget summary, plus relevant pending edit fields.
- **Outputs** · Allowed intent, draft or updates, change instructions, clarification and reply.
- **Example** · “Make Day 2 more relaxed” produces `edit` plus a Day 2 instruction.

**Visual.** Show four input arrows feeding **InterpreterResult**. Label the inputs **Questionnaire + draft**, **Latest message + recent history**, **Active plan + pending edit**, and **Local date + timezone**. On the output side show this simplified projection. Mark it **Selected fields**.

```text
intent = edit
request_updates = no changed trip-level fields
change_instructions = Reduce Day 2 activity density and leave more rest time.
clarification_question = null
```

**Speaker notes.** The interpreter receives context in one JSON data message. It can use the configured timezone to interpret a relative date and can classify a hypothetical question without turning it into an edit. New trips use `request_draft`. Existing plans use non-null `request_updates`, so omission preserves the prior value. Explicit clearing is separate and allowed for budget and start date. Internal generation checkpoints and the plan’s storage envelope stay out of interpreter context. A free-form local-action intent from the model still passes through the same Python dispatcher. The terminal history lives on disk, and only the recent slice is forwarded each time.

**Code reference.** `Interpreter.interpret()`, `InterpreterResult`, `Application.interpret()`, `prompts/interpreter.txt`.

### Slide 12 · Request normalization and budget meaning

**On-slide copy**

- A trip needs destinations and a duration of 1–21 days.
- Defaults are one traveler, balanced pace, no spending limit and numbered days when undated.
- An explicit currency takes precedence. Otherwise use the shared local currency or THB for mixed destination currencies.
- A per-person budget becomes a group budget once an explicit traveler count is known.

**Visual.** Show three worked examples with their inputs and outcomes. **Tokyo + Kyoto, no stated currency → JPY**. **Tokyo + Seoul, no stated currency → THB**. **JPY 30,000 per person × 2 explicit travelers → JPY 60,000 group limit**. Add a callout on the last example **A traveler-count-only edit preserves the normalized group limit**.

**Speaker notes.** `RequestDraft` permits missing fields. `normalize_request()` trims and deduplicates destination labels while preserving their order, derives a title if omitted, checks positive budgets and traveler counts, and requires a three-letter currency code. Local destination currencies are supplied by interpretation. A stated budget with an ambiguous currency, such as a bare dollar sign, requires clarification. Per-person conversion requires the traveler count to be explicitly supplied, so the default one traveler cannot silently stand in for it. The model estimates currency conversions when needed and the prompt requires it to disclose its assumptions. Python enforces a single reporting currency for every cost line.

**Code reference.** `normalize_request()`, `Application.interpret()`, `prompts/interpreter.txt`, `prompts/planning_rules.txt`.

### Slide 13 · The route outline defines each day’s boundaries

**On-slide copy**

- The planner proposes one outline for the entire trip before generating daily schedules.
- Every day has assigned destinations, a start city, an end city and an overnight base.
- The following day starts where the preceding day ends.
- A change of city requires an incoming transfer with endpoints, mode and travel duration.

**Visual.** Use the following illustrative outline table. The time is a sample requirement for the example route. Keep it separate from the actual model output.

| Day | Start | End | Overnight base | Incoming transfer |
| --- | --- | --- | --- | --- |
| 1 | Tokyo | Tokyo | Central Tokyo hotel | None |
| 2 | Tokyo | Tokyo | Same Tokyo hotel | None |
| 3 | Tokyo | Kyoto | Central Kyoto hotel | Tokyo to Kyoto by rail, 150 minutes |

**Speaker notes.** The outline call receives the validated request, the current plan for edits, change instructions and optional feedback. `PlanningOutline` adds trip-wide summary, assumptions, warnings and a clarification branch. Each `DayOutline` also has a day number, title, destination labels, instructions and `reuse_existing`. The prompt assigns intercity movement to the arrival day to give independent workers an agreed location and transfer. Python checks consecutive day numbers, boundary continuity, incoming transfer alignment and the requested labels in order for non-delegated trips. An invalid outline gets one repair attempt in a planning run. If the model asks a feasibility question such as “Would you rather add a day or visit fewer cities?”, the app can return to clarification before spending calls on days.

**Code reference.** `Planner.plan()`, `Planner._validate_outline()`, `PlanningOutline`, `DayOutline`, `prompts/outline.txt`.

### Slide 14 · Day generation runs concurrently

**On-slide copy**

- Each worker receives a validated request, shared outline and one day assignment.
- The default is three concurrent jobs. The setting accepts one to four.
- Responses can finish out of order. The main thread checkpoints each typed day candidate.
- Ordered validation joins the days into one itinerary.

**Visual.** Draw a timing diagram with a top lane for **Main thread** and three worker lanes. Start all lanes after **Outline saved**. End the worker bars in this illustrative order **Day 3**, **Day 2**, **Day 1**. At each completion, show an arrow to **`ready_days` keyed by day number**. After all three responses, show **Validate 1, then 2, then 3**. Label the timing **Illustrative, no latency measurement**.

**Speaker notes.** `ThreadPoolExecutor` runs up to the configured number of day jobs or the number of missing days, whichever is smaller. It starts more jobs as capacity frees, avoiding a queue of every remaining day. A worker gets adjacent outline entries and, when available, relevant fixed neighbors or the corresponding old day. It never needs an unfinished worker’s response to start. Workers send progress, parsed responses and usage metadata through a `SimpleQueue`. The main thread writes checkpoints and updates the terminal. An invalid typed result can be saved before its repair completes. If a failure or clarification arrives, the planner stops starting additional work and drains in-flight jobs. Parallelism overlaps requests. End-to-end time still depends on model, network and repair work.

**Code reference.** `Planner._fetch_days()`, `Planner.plan()`, `prompts/day.txt`, `Config.planner_workers`.

### Slide 15 · Validation feedback drives targeted repair

**On-slide copy**

1. A worker checks its day against local schedule rules and the outline.
2. The main thread checks the assembled prefix for cross-day conflicts.
3. A repair call receives the affected day, a specific error and available fixed neighbors.
4. The repaired day re-enters validation before the plan can be saved.

**Visual.** Draw **Candidate day → Local checks → Ordered prefix checks → Accepted**. From both checks, draw a loop into **Repair this day**. Under the local loop use **Missing walk from shrine to lunch**. Under the ordered loop use **Day 1 ends at 00:30 on the next day. Day 2 starts at 00:15 in the same zone.** Show a corrected Day 2 start at **00:45** for the overlap example.

**Speaker notes.** Shape validation comes first when the provider result is parsed. Local validation can find a malformed timeline, missing meal, missing connection, wrong currency or an absent outlined transfer. Each worker can request one repair inside the same concurrency slot. The ordered pass can catch issues an isolated day cannot see, such as a midnight overlap or an inconsistent route between days. It repairs the first failing day against available fixed context and keeps other candidates. In this ordered pass, a generated or cached non-reused day normally gets one repair call and a reused day can get up to two. If repair is exhausted, the app surfaces the issue and retains its checkpoint for explicit Retry. The day prompt asks the model to preserve unaffected content.

**Code reference.** `Planner._fetch_days()`, `Planner.plan()`, `validate_independent_day()`, `validate_day_prefix()`, `prompts/day.txt`.

## Part III · Schedule integrity, revisions and output

### Slide 16 · Time, destination and transfer checks

**On-slide copy**

- Local time, timezone and day offset determine elapsed time and overlap.
- A requested destination needs an actual scheduled visit, such as an activity or meal.
- Travel connects successive visits at different places, including short walks.
- A multi-leg transfer must connect its endpoints and meet the outline’s minimum travel time.

**Visual.** Use two worked examples. For time, show **23:40 on Day +0 to 00:20 on Day +1, same zone = 40 minutes**. For routing, show **Hotel A → Departure airport → Arrival airport → Hotel B**. Label the three travel legs **35 min**, **120 min** and **45 min**, for **200 min of travel**. Show a separate **45 min airport wait** with the caption **Waiting adds elapsed schedule time and contributes zero travel minutes**.

**Speaker notes.** Each item stores 24-hour start and end times, an IANA timezone or explicit UTC offset for each endpoint, nonnegative day offsets and a duration. Python converts the endpoints to UTC and checks duration and chronological ordering across the itinerary. Undated trips keep dates null and use a representative date for arithmetic. A plan still needs meals and rest or free time each day. The full validation checks destination coverage and first-visit order unless destination choice was delegated. A route can be a chain of timed segments if each segment ends where the next begins. Visit and transfer checks compare normalized names. They cannot establish whether the locations are geographically correct or whether the estimated time matches a real timetable.

**Code reference.** `_instant()`, `_check_days()`, `_check_visit_connections()`, `validate_day_outline()`, `_has_transfer_route()`.

### Slide 17 · Python computes the budget from line items

**On-slide copy**

| Offline fixture | Group cost |
| --- | ---: |
| Accommodation | JPY 33,000 |
| Food | JPY 12,000 |
| Transport | JPY 16,220 |
| Activities | JPY 4,600 |
| Other | JPY 0 |
| **Estimated total** | **JPY 65,820** |

- Group limit **JPY 75,000**. Remaining **JPY 9,180**.
- Unknown costs make the total partial and the budget status uncertain.

**Visual.** Use the table or a horizontal bar chart based on the category rows. Put the arithmetic **JPY 75,000 − JPY 65,820 = JPY 9,180 remaining** next to it. Label all figures **Offline fixture estimates for the whole group**.

**Speaker notes.** Each cost belongs to a schedule item or a day’s additional costs, such as accommodation. The model supplies estimates. Python checks for a nonnegative amount and the reporting currency, sums via `Decimal(str(amount))` and derives day, category and group totals plus remaining budget. A zero amount means free. A null amount means unknown. Known amounts still contribute to the partial total, but any unknown cost yields `uncertain`. With complete costs, the app distinguishes `no_limit`, `within_budget` and `over_budget`. A valid over-budget plan can commit with a warning. The scope includes accommodation, meals, activities, local transport and transfers between requested destinations. Home-to-first and last-to-home travel are outside the default scope. The fixture’s day totals are JPY 17,660, JPY 17,660 and JPY 30,500.

**Code reference.** `Cost`, `BudgetSummary`, `_cost_amount()`, `build_plan()`, `demo_plan()`.

### Slide 18 · What a targeted edit regenerates

**On-slide copy**

- “Make Day 2 more relaxed” can leave the normalized trip request identical.
- The outline marks unaffected days as reusable.
- The planner can generate Day 2 and carry Days 1 and 3 into the full candidate.
- All three days pass ordered validation before revision 2 commits.

**Visual.** Show two rows with columns **Day 1**, **Day 2**, **Day 3**. Label the upper row **Committed revision 1**. In the lower row label Day 1 **Copy**, Day 2 **Regenerate**, Day 3 **Copy**. Enclose the lower row in a bracket labeled **Full candidate → Ordered validation → Revision 2**. Add a second, smaller example **Change duration to four days → New outline and fresh day generation**.

**Speaker notes.** The interpreter expresses the relaxation request as change instructions and leaves trip-level pace alone unless the user asks to change it for the whole trip. The outline sees the existing plan and can set `reuse_existing=true` for days that can be copied exactly. Python adds a second condition, equality between the current and newly normalized `TripRequest`. Copied days still face outline and ordered checks. If a revised transfer affects a neighboring day, the outline should flag that day for regeneration, and a copied day that fails validation can be repaired. For schedule identity, Python can retain a valid prior item ID or match an unclaimed old item by kind, title and place. It assigns a UUID to new items and checks uniqueness. The stored result is one complete replacement revision.

**Code reference.** `Planner.plan()`, `prompts/outline.txt`, `prompts/day.txt`, `build_plan()`, `tests/test_recovery.py`.

### Slide 19 · Checkpoints preserve out-of-order work

**On-slide copy**

- `outline` stores the approved route.
- `days` stores the contiguous validated prefix. `ready_days` holds candidates awaiting ordered acceptance.
- If Day 2 fails while Day 3 finishes, Day 3 stays available for Retry.
- A compatible Retry requests missing work and rechecks saved candidates.

**Visual.** Draw this illustrative checkpoint state at the point of failure. **Outline saved**, **Accepted prefix [Day 1]**, **Ready candidates {3: Day 3}**, **Missing Day 2**. Draw `Retry` with an arrow to a single new **Day 2 request**, then draw **Ordered validation of Day 2 and Day 3**. Annotate **If a cached day fails validation, repair it before acceptance**.

**Speaker notes.** `Application.generate()` passes a save callback to the planner, which writes the generation state to `session.pending.generation`. The state includes a checkpoint identity, outline, prefix, ready candidates, reused-day markers, call metadata and any current invalid candidate/feedback. On worker failure the app stops new submissions, drains in-flight responses and advances any valid contiguous prefix before exposing the failure. A SHA-256 identity covers planning context, including the normalized request, current plan context and change instructions, plus planner model, active prompts and checkpoint version. A context, model or prompt change invalidates the checkpoint. Changes to workers, timeout, token caps or reasoning effort can retain completed work. The user must explicitly retry an interrupted operation after restart. A complete compatible checkpoint can finish without new model calls.

**Code reference.** `Planner.plan()`, `Planner._fetch_days()`, `Application.generate()`, `Application.recover()`.

### Slide 20 · The commit marker and the local files

**On-slide copy**

| File under `output/<trip-id>/` | Purpose |
| --- | --- |
| `session.json` | Draft, current stage and generation checkpoint |
| `conversation.json` | Separate transcript copy |
| `revisions/0001.json`, `0002.json`, … | Full revision snapshots |
| `request.json` | Copy of the normalized request |
| `plan.json` | Authoritative committed revision |
| `itinerary.html` | Derived browser view |

**Visual.** Pair the table with a numbered sequence **1. Write revision snapshot · 2. Write request copy · 3. Replace plan.json · 4. Persist chat state · 5. Render HTML**. Highlight step 3 as the commit marker. Add **One writer per trip folder** below the sequence.

**Speaker notes.** Each JSON or HTML write uses a temporary file in the target directory, flushes and syncs it, and replaces the target. That protects an existing file from a partial rewrite. The files do not share one transaction and there is no multi-process writer lock. If interrupted before the commit marker, a newer snapshot or request copy may already exist while the old plan remains authoritative. If `plan.json` advanced before the session write completed, resume detects a pending base revision older than the committed revision and supersedes that pending operation. A failed plan write can be retried with the same validated candidate in memory. A failed HTML render can be retried from committed JSON without regenerating the plan. Saved trips use safe identifiers, and loading checks that the saved identity matches its folder.

**Code reference.** `Store.save_session()`, `Store.save_plan()`, `Store.load_plan()`, `atomic_text()`, `Application.commit()`, `Application.run()`.

### Slide 21 · The browser document derives from committed JSON

**On-slide copy**

- Jinja renders the validated plan with packaged styles into one HTML file.
- Day navigation links to each schedule. Transfer rows show endpoints, mode and duration.
- The budget and assumptions sit beside the timeline. Revision details appear in the footer.
- The page opens locally and supports browser printing to PDF.

**Visual.** Draw a page wireframe. Top row **Title, route, duration and travelers**. Second row **Warnings and day links**. Main left column **Day 3 timeline with a train block**, main right column **JPY 65,820 estimated group total, costs by category, assumptions**. Footer **Revision 1 · Offline fixture · Generation record**. Use the exact figure and route already supplied for the fixture.

**Speaker notes.** `Application.show_page()` reloads and validates the committed JSON before rendering. Jinja autoescapes trip and model text. The renderer only marks the packaged CSS as trusted markup and embeds it in the page. The itinerary needs no external assets or browser app server. It shows unknown costs explicitly, and text amounts accompany budget bars. Revision and provider/model information help readers see what produced the plan. After a change the renderer replaces the same HTML path. Refreshing reads the new revision. If the browser launch fails, the app still prints the path. The offline `render` command can rebuild the page from a saved plan.

**Code reference.** `Application.show_page()`, `render_plan()`, `itinerary.html.j2`, `static/styles.css`.

## Part IV · Demonstration and evidence

### Slide 22 · Offline demo walkthrough

**On-slide copy**

1. Generate the packaged sample.
2. Open the printed HTML path and jump to Day 3.
3. Show the intercity transfer and budget breakdown.
4. Rebuild the same HTML from the saved JSON.

```sh
python -m trip_planner demo --no-open
python -m trip_planner render --plan output/TRIP_ID/plan.json --no-open
```

**Visual.** Use the command block alongside a two-part itinerary excerpt. Show **Day 3 · 08:00–10:30 Tokyo to Kyoto**, then **JPY 65,820 estimated · JPY 9,180 remaining**. Include **Offline example, revision 1** as a caption. These details can stand in for a screenshot when presenting without the app.

**Speaker notes.** Install the Python package beforehand with `python -m pip install -e .` from the project directory. For the render command, replace the sample path with the absolute `plan.json` path printed by the first command, especially if the output directory is customized. The demo fixture creates three undated days for one traveler at a balanced pace, stores the plan and opens no browser under `--no-open`. The presenter manually opens the resulting file. Day 3 shows the estimated rail window, an arrival buffer and an afternoon visit to Fushimi Inari. The demo and render commands need no credentials. They exercise validation, budget calculation, storage and rendering using fixed data. To explain the live AI path, return to the clearly labeled interpreter, repair and retry examples on slides 11, 15 and 19.

**Code reference.** `cli.main()`, `demo_plan()`, `README.md`.

### Slide 23 · What the tests verify

**On-slide copy**

| Area | Example checked by the suite |
| --- | --- |
| Parallel generation | Overlapping calls, worker limit and out-of-order checkpointing |
| Recovery and edits | Failed day resumes, compatible checkpoints survive and unchanged days can be reused |
| Schedule and transfer rules | Cross-day overlaps and disconnected travel legs are rejected or repaired |
| Provider handling | Structured streams, timeouts, incomplete output and refusals over mocked HTTP |
| Storage | A newer committed plan supersedes stale pending state |

**Visual.** Place the table beside **48 repository tests passed** and **Offline demo and render completed**. Under the figure show the test command `python -m unittest discover -s tests -v`. Label this evidence **Current checkout · offline verification**.

**Speaker notes.** Parallel tests use controlled completion events so a later day can finish before an earlier one. Recovery tests use injected services to observe which days are requested and which are kept. Provider tests exercise the SDK response parser with a mock transport. The offline demo and a separate render of its saved JSON verify the user-visible output path. This evidence covers behavior in the code and fixture. Live latency, model quality and real travel accuracy are outside the measurements.

**Code reference.** `tests/test_parallel.py`, `tests/test_recovery.py`, `tests/test_transfers_storage.py`.

### Slide 24 · Where the itinerary needs traveler judgment

**On-slide copy**

- Python validates schedule structure, transfer connections and cost arithmetic.
- Travel time, hours, prices, availability and exchange rates are estimates.
- Live planning sends selected trip context to OpenAI. The local trip files are unencrypted.
- The traveler decides whether to clarify, revise, retry or act on the plan.

**Visual.** Use three labeled rows. **Validated locally** with an example **No overlapping schedule blocks**. **Estimated by the model** with **Rail duration and group costs**. **Decided by the traveler** with **Confirm the actual train and make a reservation**. Put a small footer under the diagram **The app has no live routing, timetable, price, weather or booking integration**.

**Speaker notes.** A schedule can be internally consistent and still require checking that a train runs, a site is open or a route is accessible. The application verifies internal constraints using structured data and name matching. It does not fetch current conditions or book travel. The local design keeps drafts and revisions on the user’s machine, and live calls still transmit relevant answers and plan context. The code requests `store=False` for provider calls. Explain that as a request option and avoid making broader provider-retention claims. Close by pointing back to the three-day example. The traveler can see the assumptions, inspect the estimated cost and change the itinerary while retaining prior saved work.

**Code reference.** `trip_planner/validation.py`, `trip_planner/openai_service.py`, `prompts/planning_rules.txt`, `DOC.md`.

## Appendix · Technical reference slides

### Slide 25 · Key data contracts and ownership

**On-slide copy**

| Contract | Essential fields | Owner |
| --- | --- | --- |
| `RequestDraft` / `TripRequest` | Destinations, duration, group budget and currency, travelers, pace, preferences, optional start date | Interpretation proposes. Python normalizes. |
| `PlanningOutline` / `DayOutline` | Numbered day assignments, city boundaries, overnight base, transfer, reuse marker | Model proposes. Python checks. |
| `DayPayload` / `ScheduleItem` | Date, destinations, timed items, travel details, item costs and additional costs | Model proposes. Python checks. |
| `SavedPlan` | Trip ID, schema version, revision, UTC timestamps, schedule IDs, computed totals and generation metadata | Python constructs and persists. |

**Visual.** Use the table with a small containment diagram beneath it. **SavedPlan** contains **TripRequest**, **Days**, **BudgetSummary** and **GenerationMetadata**. **Day** contains **ScheduleItems**, **Additional costs** and **Estimated total**. **ScheduleItem** contains **Cost** and optional **Travel**.

**Speaker notes.** Pydantic contracts reject unexpected fields and non-finite numeric values. `InterpreterResult` carries both interpretation data and intent. `DayResult` carries a day or a clarification branch, and `PlannerResult` wraps the assembled itinerary or a question. Schedule kinds are activity, meal, travel, rest and free time. `Travel` has origin, destination, mode, duration and route notes. Costs carry category, amount, currency and an optional label. The committed plan uses schema version `1.0`. On load, `validate_plan()` checks the version, revision, UTC timestamps and stable IDs, rechecks domain rules and verifies saved totals against itemized amounts. Model estimates and Python-derived totals occupy separate fields.

**Example record for the speaker or visual.** The offline fixture’s Day 3 rail item has `kind="travel"`, `start_time="08:00"`, `end_time="10:30"`, both timezones set to `Asia/Tokyo`, both offsets set to `0`, and `duration_minutes=150`. Its nested travel record gives Tokyo as the origin, Kyoto as the destination and 150 estimated travel minutes. Its nested cost is `category="transport"`, `amount=14500`, `currency="JPY"`. That cost contributes once to the Day 3 total and once to the transport category subtotal. The item’s stable ID belongs to the saved plan.

**Code reference.** `trip_planner/models.py`, `build_plan()`, `validate_plan()`.

### Slide 26 · Model calls, streaming and retry controls

**On-slide copy**

| Control | Repository default |
| --- | --- |
| Role model | `OPENAI_MODEL` or the corresponding role override. No hardcoded model. |
| Output cap per call | 2,000 tokens for interpretation. 6,000 for planning. |
| Reasoning effort | `low`. Set `default` to omit the option. |
| Inactivity and elapsed guard | 90 seconds and 300 seconds, respectively |
| SDK retries | 0 |
| Day workers | 3, configurable from 1–4 |

**Visual.** Put the table beside a five-step boundary diagram. **System prompt + JSON context → Responses stream → Consume events → Parse final result → Validate in Python**. Label the error exit **Safe terminal message + recovery prompt**.

**Speaker notes.** The application calls `responses.stream` with a Pydantic output format and `store=False`. It consumes events for progress and only returns a completed parsed result. An event can trigger a heartbeat about every 15 seconds. The elapsed guard is checked between received events, so it is not a strict interruption timer for an already blocked read. The SDK timeout and SDK retry policy are separate from domain repair calls and the traveler’s explicit Retry. The shared planner service initializes its SDK client under a lock and stores per-call metadata in thread-local storage. Planner usage is aggregated across recorded calls, including compatible checkpointed calls from before a restart. Environment variables override `.env`. A simple three-day create with no clarification or repairs ordinarily uses one interpretation, one outline and three day calls. Reuse can reduce day calls on edits. Extra interpretation or repair can add calls.

**Code reference.** `Config.load()`, `OpenAIService.parse()`, `OpenAIService._get_client()`, `Planner.plan()`.

### Slide 27 · Entry points and failure handling

**On-slide copy**

| Entry point | Starts with | Network behavior |
| --- | --- | --- |
| `python -m trip_planner` | Saved-trip menu or questionnaire | Model calls when interpreting or planning |
| `generate --text-file answers.txt` | Labeled answers | Interprets and plans |
| `chat --plan path/to/plan.json` | A committed plan in its trip folder | Local actions offline. Free text can call the model. |
| `demo --no-open` | Packaged example | Offline |
| `render --plan path/to/plan.json` | Validated saved JSON | Offline |

**Visual.** Under the table place a small recovery matrix with four rows. **Model call fails · Retry the saved operation**. **Conflict · Answer the clarification or cancel a pending edit**. **Plan write fails · Retry saving the in-memory candidate**. **HTML write fails · Retry rendering from committed JSON**.

**Speaker notes.** Prefix each subcommand with `python -m trip_planner` or the installed `trip-planner` command. For the answer-file path, provide labeled lines such as `Trip name: Japan food and temples`, `Days: three days`, `Destinations: Tokyo then Kyoto`, `Budget: JPY 75,000 for the group` and `Preferences: quieter mornings and Fushimi Inari`. The CLI reads labels while the interpreter extracts meaning. The `chat` command expects a file named `plan.json` in the trip’s application-created folder. The renderer accepts a valid saved plan path and writes `itinerary.html` beside it. During recovery, a provider timeout, output limit or quota failure has a specific terminal message. Credential values and raw provider error bodies are excluded from the app’s messages. The app uses the authoritative plan to recover the browser view.

**Code reference.** `cli.main()`, `read_answers()`, `Application.recover()`, `Application.commit()`, `Application.show_page()`.
