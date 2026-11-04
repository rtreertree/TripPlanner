"""Small argparse entry point. Offline commands never construct an API client."""

import argparse
from pathlib import Path
import re
from uuid import uuid4
import webbrowser

from pydantic import ValidationError

from .config import Config
from .conversation import Application
from .models import RequestDraft, SavedPlan
from .renderer import render_plan
from .storage import Session, Store
from .validation import validate_plan


def parser():
    result = argparse.ArgumentParser(description="Describe a trip, view an itinerary, and refine it in terminal chat.")
    result.add_argument("--no-open", action="store_true", help="Do not automatically open a browser")
    result.add_argument("--output-dir", type=Path, help="Saved-trip directory (default: output)")
    commands = result.add_subparsers(dest="command")
    for name, description in [("generate", "Generate from labeled natural-language answers"),
                              ("chat", "Resume a saved plan"), ("render", "Render a saved plan offline"),
                              ("demo", "Create a clearly labeled offline example")]:
        command = commands.add_parser(name, help=description)
        command.add_argument("--no-open", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("--output-dir", type=Path, default=argparse.SUPPRESS)
        if name in {"chat", "render"}:
            command.add_argument("--plan", type=Path, required=True)
        if name == "generate":
            command.add_argument("--text-file", type=Path, required=True)
    return result


def read_answers(path: Path) -> dict[str, str]:
    """Read labels only; the interpreter, rather than Python, extracts their meaning."""
    aliases = {"trip name": "trip_name", "days": "duration_days", "destinations": "destinations",
               "budget": "budget", "preferences": "preferences", "preferences / special requests": "preferences"}
    answers, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        label, separator, value = line.partition(":")
        label = re.sub(r"\s*\(optional\)\s*", "", label, flags=re.IGNORECASE).strip().casefold()
        if separator and label in aliases:
            current = aliases[label]
            answers[current] = value.strip()
        elif line.strip() and current:
            answers[current] += "\n" + line.strip()
    if "duration_days" not in answers or "destinations" not in answers:
        raise ValueError("The answer file needs labeled Days: and Destinations: lines. See examples/trip_answers.txt.")
    return {field: answers.get(field, "") for field in ["trip_name", "duration_days", "destinations", "budget", "preferences"]}


def open_page(path):
    print(f"Infographic: {path.resolve()}")
    try:
        opened = webbrowser.open(path.resolve().as_uri())
    except (OSError, webbrowser.Error):
        opened = False
    if not opened:
        print("Open the HTML path above in your browser.")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "render":
            plan = validate_plan(SavedPlan.model_validate_json(args.plan.read_text(encoding="utf-8")))
            path = render_plan(plan, args.plan.resolve().parent / "itinerary.html")
            print(f"Saved infographic: {path.resolve()}")
            if not args.no_open:
                open_page(path)
            return 0
        config = Config.load()
        store = Store(args.output_dir or config.output_dir)
        if args.command == "demo":
            from .demo import demo_plan
            plan = demo_plan().model_copy(update={"trip_id": uuid4().hex})
            store.save_plan(plan)
            store.save_session(Session(trip_id=plan.trip_id, stage="chat", draft=RequestDraft.model_validate(plan.request.model_dump())))
            path = render_plan(plan, store.directory(plan.trip_id) / "itinerary.html")
            print(f"Offline demo — sample estimates, no AI calls. Saved JSON: {store.directory(plan.trip_id) / 'plan.json'}")
            print(f"Saved infographic: {path.resolve()}")
            if not args.no_open:
                open_page(path)
            return 0
        from .interpreter import Interpreter
        from .planner import Planner
        app = Application(config, store, Interpreter(config), Planner(config), no_open=args.no_open)
        session = None
        if args.command == "generate":
            config.validate_live()
            answers = read_answers(args.text_file)
            session = Session(answers=answers, skipped=[key for key, value in answers.items() if not value],
                              prompt_index=5, stage="interpret")
            store.save_session(session)
        elif args.command == "chat":
            plan_path = args.plan.resolve()
            plan = validate_plan(SavedPlan.model_validate_json(plan_path.read_text(encoding="utf-8")))
            if plan_path.name != "plan.json" or plan_path.parent.name != plan.trip_id:
                raise ValueError("Resume the plan.json inside its application-created trip folder.")
            store = Store(plan_path.parent.parent)
            app.store = store
            session = store.load_session(plan.trip_id)
        app.run(session, resume_operation=args.command != "generate")
        return 0
    except (OSError, ValueError, ValidationError) as exc:
        # Never print environment contents or provider exception bodies.
        if isinstance(exc, ValidationError):
            print("The saved file is not a valid trip-planner document. Your existing files were preserved.")
        elif isinstance(exc, OSError):
            print(f"Could not read or write a local file ({type(exc).__name__}). Check its path and permissions.")
        else:
            print(str(exc))
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Previously saved work is preserved.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
