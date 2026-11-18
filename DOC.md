# Local Trip Planner reference

For installation and a first itinerary, start with the [README](README.md#run-the-offline-demo).

## Commands

Run commands from the directory containing your `.env`. After installation, `trip-planner` and `python -m trip_planner` are equivalent.

| Task | Command |
| --- | --- |
| Start a trip or choose a saved draft or plan | `python -m trip_planner` |
| Create the offline example | `python -m trip_planner demo --no-open` |
| Plan from a text file, then enter chat | `python -m trip_planner generate --text-file answers.txt` |
| Resume a committed trip | `python -m trip_planner chat --plan output/TRIP_ID/plan.json` |
| Rebuild an itinerary page offline | `python -m trip_planner render --plan output/TRIP_ID/plan.json --no-open` |
| Show available options | `python -m trip_planner --help` |

Replace `output/TRIP_ID/plan.json` with your saved plan path. `chat` expects `plan.json` inside its original trip folder. `render` writes `itinerary.html` beside its input. Use `--no-open` to suppress automatic browser opening. Use `--output-dir PATH` to choose where to create or look for trips at startup.

## Answer-file example

Save the following as `answers.txt` and run the `generate` command above. Include both `Days:` and `Destinations:`. The other labels are optional. A nonblank continuation line belongs to the preceding answer, with or without indentation.

```text
Trip name: Japan Food and Culture
Days: three days
Destinations: Tokyo first, then Kyoto
Budget: 75,000 yen for the whole trip
Preferences / special requests: One traveler. I like local food and quiet temples.
  Include Fushimi Inari on Day 3 and leave time for the train from Tokyo.
```

The interactive questionnaire asks for the same five fields. Press Enter or type `skip` for an optional field. Type `back` to revisit an answer, `help` for an example, or `exit` to save the draft. The interpreter reads the answers together and asks for clarification when necessary.

## Configuration

Existing environment variables take precedence over the current directory's `.env`. The defaults below apply when a setting is absent. In particular, the example file selects `Asia/Bangkok`, while the application default is `UTC`. Restart the app to load configuration changes. [Example configuration](.env.example)

| Setting | Default | Use |
| --- | --- | --- |
| `OPENAI_API_KEY` | Unset | Credential for live questions and planning. |
| `OPENAI_MODEL` | Unset | Shared model for interpretation and planning. Select one that supports Responses Structured Outputs. |
| `OPENAI_EXTRACTOR_MODEL` | Shared model | Override the model that interprets answers and chat. |
| `OPENAI_PLANNER_MODEL` | Shared model | Override the model that generates the outline and daily schedules. |
| `OPENAI_REASONING_EFFORT` | `low` | Applies to both roles. Use `default` or an empty value to let the model choose. |
| `TRIP_PLANNER_WORKERS` | `3` | Generate 1–4 days at a time. Use `1` for sequential generation. |
| `OPENAI_TIMEOUT_SECONDS` | `90` | Network inactivity timeout. The SDK timeout is capped by the request deadline and connection setup is capped at 10 seconds. |
| `OPENAI_REQUEST_DEADLINE_SECONDS` | `300` | Elapsed-time limit for one API call, checked as stream events arrive. A blocked read can delay the check. |
| `OPENAI_MAX_RETRIES` | `0` | Allow 0–3 SDK retries when opening a request. |
| `OPENAI_EXTRACTOR_MAX_OUTPUT_TOKENS` | `2000` | Output limit per interpretation response. |
| `OPENAI_PLANNER_MAX_OUTPUT_TOKENS` | `6000` | Output limit per outline, day, or repair response. |
| `TRIP_PLANNER_TIMEZONE` | `UTC` | IANA timezone for interpreting relative dates such as “next Friday.” |
| `TRIP_PLANNER_OUTPUT_DIR` | `output` | Root folder for saved trips. An explicit `--output-dir` takes precedence when selecting this root. |

## Trip and budget defaults

Trips span 1–21 days. The defaults are one traveler, a balanced pace, numbered days, and no spending limit. For a stated budget, supply a currency. A per-person budget also needs an explicit traveler count so the app can convert it to a group total. A later change to the traveler count alone preserves that total.

Without a specified reporting currency, the app uses the destinations' shared local currency or THB for destinations with different currencies. Group estimates cover accommodation, meals, activities, local transport, and transfers between destinations. Ask explicitly to include the journey from home or the return trip.

## Recovery and revisions

| What you see or want to do | What to do |
| --- | --- |
| A request timed out or planning stopped partway through | Type `Retry`. After a restart, select the saved trip first. During generation the app uses the saved outline and day responses, requests missing work, and repairs invalid days as needed. If interpretation was interrupted, retry repeats that interpretation step. |
| The app reports an output limit | Increase the setting named in the message, restart, select the trip, and type `Retry`. Changing token limits, timeouts, reasoning effort, or worker count preserves compatible checkpoints. |
| The latest progress or itinerary could not be saved | Check write access to the trip folder and type `Retry` at the save prompt. The running session retries the disk write with the data it already holds. |
| The plan is saved but its page could not be created | Correct the filesystem issue and type `Retry` in chat, or run `render` against the saved JSON. Both rebuild the page offline. If only the browser failed to open, open the printed path directly. |
| You want to abandon a pending edit | Type `Cancel` during clarification or at the recovery prompt for a saved plan. The app discards the pending change and restores the saved request. |
| You want to reverse a committed edit | Type `Undo my last change`. The app copies the previous revision into a new revision. Refresh the page to see it. Undo is available from revision 2 onward. |

Use `Show my plan`, `Open the infographic`, or `List my saved trips` for local access during an outage. Questions about the itinerary and requests to change it use the live service.

## How a trip becomes a saved plan

1. **Interpret the request.** The interpreter turns labeled answers or a chat message into a question, an action, or proposed trip details. Python merges explicit changes into the draft, asks about missing details, and normalizes the request before planning. An itinerary question can be answered without creating a revision.
2. **Generate the outline and days.** The planner establishes each day's start, end, overnight base, and incoming transfer. Workers generate missing days against that outline. Each worker checks its day and can request one local repair. The main thread saves responses as they arrive, including later days that finish first. On edits, the planner can reuse days marked unaffected when normalized trip constraints match.
3. **Validate the days in order.** The app checks the growing sequence for overnight overlaps, requested destination order, and connecting transfers. A journey can span several legs, such as taxi → flight → taxi. Each endpoint must connect and only travel minutes count toward the required transfer duration. Local times and day offsets are compared in UTC. Undated trips use a representative date, so seasonal clock changes need confirmation. A boundary error can trigger a repair of the affected day using its neighbors.
4. **Compute costs and commit.** Python assigns IDs to new schedule items and sums itemized expenses using decimal arithmetic. Zero means free. An unknown amount contributes nothing to the known subtotal and marks the budget status uncertain. Once validation succeeds, the app writes the revision snapshot and normalized request, then replaces `plan.json`. It saves the session and renders the HTML from the committed plan.

Checkpoints are tied to planning inputs, including the request, current plan context, edit instructions, model, and prompts. A compatible restart can reuse both the validated sequence of days and later responses waiting for earlier days. [Planner implementation](trip_planner/planner.py) · [Validation rules](trip_planner/validation.py) · [Data models](trip_planner/models.py)

## Saved files and privacy

| File under `output/<trip-id>/` | Purpose |
| --- | --- |
| `session.json` | Resume a draft or interrupted operation. Includes answers, prompt position, conversation stage, pending instructions, and generation checkpoints. |
| `conversation.json` | Read the saved conversation history. |
| `plan.json` | Authoritative committed itinerary, including the revision number, validated days, budget, and generation metadata. |
| `request.json` | Inspect the normalized request written during a plan commit. |
| `revisions/0001.json`, … | Recover content from prior revisions for undo. |
| `itinerary.html` | Open, print, or regenerate the standalone itinerary page. |

Keep the whole folder to preserve both revision history and resumable work. Each file is replaced atomically. A crash between writes can leave a newer snapshot or request on disk, so recovery uses the revision in `plan.json` to determine which plan was committed. A draft can contain only session and conversation files. Use one running writer per trip.

Live interpretation sends the labeled answers, draft, current message, up to 12 recent messages, and relevant pending edits. For an active trip it also includes itinerary and budget context. Planning sends the normalized request, edit instructions, and the outline or itinerary details needed for the call. The SDK uses `store=False`. The local files are unencrypted, and the HTML includes trip details. Review it before sharing.

## Offline verification

From the installed checkout, run the regression suite and inspect the CLI without credentials.

```sh
python -m unittest discover -s tests -v
python -m trip_planner --help
```

For a storage and rendering smoke check, run the offline demo and pass its printed JSON path to the `render` command. The rebuilt HTML should appear beside the plan and open directly in a browser. Travel times, prices, hours, and availability still need checking before booking.
