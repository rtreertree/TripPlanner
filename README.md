# Local Trip Planner

Describe a trip in the terminal and open a day-by-day itinerary in your browser. You can ask why a stop was included, change a day, or return to an earlier revision.

> ▶ **[Watch the Local Trip Planner video on YouTube](https://www.youtube.com/watch?v=cMlg8V54Uzo)**

> ▶ **[See self assesment form (require chula.ac.th email login)](https://docs.google.com/spreadsheets/d/1jAhf9tX7GaT31XohICvmVyuJv9Jn4SFEBaTGJivHAFc/edit?usp=sharing)**


## Run the offline demo

From the project directory, use Python 3.11 or newer to install the app in a virtual environment. These commands work in a macOS or Linux shell.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m trip_planner demo --no-open
```

The demo creates a three-day Tokyo and Kyoto itinerary without an API key or network access. Look for these two lines. Your absolute paths and trip ID will differ.

```text
Offline demo — sample estimates, no AI calls. Saved JSON: /path/to/output/<trip-id>/plan.json
Saved infographic: /path/to/output/<trip-id>/itinerary.html
```

Open the printed HTML path in your browser. The page works offline and can be printed to PDF. To open the page automatically the next time you run the demo, omit `--no-open`.

## Plan your own trip

Create or update `.env` in the directory where you run the app. Set these two values, choosing a model available to your account that supports the Responses API and Structured Outputs.

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-name
```

```sh
python -m trip_planner
```

Choose **Start a new trip** if the saved-trip menu appears. Enter the number of days and destinations in travel order. Trip name, budget, and preferences are optional. If you give a budget, include its currency and say whether it covers the whole group or each traveler.

After the itinerary opens, keep the terminal open for questions and changes. For example, enter these messages one at a time.

```text
Why did you choose this neighborhood?
Make Day 2 more relaxed.
Undo my last change
Exit
```

Refresh the browser after an edit or undo. To resume, run `python -m trip_planner` again and select the trip by number or partial name. If planning was interrupted, select the draft and type `Retry` when prompted. [Recovery and revisions](DOC.md#recovery-and-revisions)

## Where your trip data goes

Drafts, revisions, and the HTML page live in `output/<trip-id>/` by default. These files are unencrypted. Live interpretation and planning send relevant trip details to OpenAI, including answers, edit instructions, and active itinerary details. The interpreter also receives recent chat history. [Saved files and privacy](DOC.md#saved-files-and-privacy)

Travel times, prices, opening hours, and availability are estimates. Confirm details before booking. For answer-file input, model settings, and output folder options, see the [command reference](DOC.md#commands), [answer-file example](DOC.md#answer-file-example), and [configuration](DOC.md#configuration).
