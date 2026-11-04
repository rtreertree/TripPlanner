"""Atomic local persistence; plan.json is the authoritative committed revision."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import RequestDraft, SavedPlan
from .validation import validate_plan


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    answers: dict[str, str] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    prompt_index: int = 0
    draft: RequestDraft = Field(default_factory=RequestDraft)
    stage: str = "collect"
    clarification: str | None = None
    pending: dict = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)
    interpretation_metadata: list[dict] = Field(default_factory=list)


def atomic_json(path: Path, data: dict) -> None:
    """A failed write never truncates an existing file."""
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def atomic_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".pending-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.warnings: list[str] = []

    def directory(self, trip_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", trip_id):
            raise ValueError("Invalid saved-trip identifier.")
        path = self.root / trip_id
        if path.is_symlink():
            raise ValueError("Saved-trip directories cannot be symbolic links.")
        return path

    def save_session(self, session: Session) -> None:
        session.updated_at = utc_now()
        folder = self.directory(session.trip_id)
        atomic_json(folder / "session.json", session.model_dump(mode="json"))
        atomic_json(folder / "conversation.json", {"messages": session.history})

    def load_session(self, trip_id: str) -> Session:
        folder = self.directory(trip_id)
        if (folder / "session.json").exists():
            session = Session.model_validate_json((folder / "session.json").read_text(encoding="utf-8"))
            if session.trip_id != trip_id:
                raise ValueError("Saved session identity does not match its folder.")
            return session
        plan = self.load_plan(trip_id)
        return Session(trip_id=trip_id, stage="chat",
                       draft=RequestDraft.model_validate(plan.request.model_dump()))

    def load_plan(self, trip_id: str) -> SavedPlan:
        plan = SavedPlan.model_validate_json((self.directory(trip_id) / "plan.json").read_text(encoding="utf-8"))
        if plan.trip_id != trip_id:
            raise ValueError("Saved plan identity does not match its folder.")
        return validate_plan(plan)

    def save_plan(self, plan: SavedPlan) -> None:
        validate_plan(plan)
        folder = self.directory(plan.trip_id)
        # Commit last. Extra history files from an interrupted write are ignored
        # until plan.json points to that revision.
        atomic_json(folder / "revisions" / f"{plan.revision:04d}.json", plan.model_dump(mode="json"))
        atomic_json(folder / "request.json", plan.request.model_dump(mode="json"))
        atomic_json(folder / "plan.json", plan.model_dump(mode="json"))

    def previous_plan(self, current: SavedPlan) -> SavedPlan | None:
        if current.revision <= 1:
            return None
        path = self.directory(current.trip_id) / "revisions" / f"{current.revision - 1:04d}.json"
        return SavedPlan.model_validate_json(path.read_text(encoding="utf-8"))

    def list_trips(self) -> list[dict]:
        self.warnings.clear()
        if not self.root.exists():
            return []
        entries = []
        for folder in self.root.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                session = self.load_session(folder.name)
                plan_path = folder / "plan.json"
                plan = self.load_plan(folder.name) if plan_path.exists() else None
                name = (plan.request.trip_name if plan else session.draft.trip_name)
                destinations = (plan.request.destinations if plan else session.draft.destinations) or []
                entries.append({"trip_id": folder.name, "name": name or session.answers.get("trip_name") or "Untitled trip",
                                "destinations": ", ".join(destinations) or session.answers.get("destinations", ""),
                                "status": "Plan" if plan else "Draft", "updated_at": session.updated_at})
            except (OSError, ValueError, ValidationError) as exc:
                self.warnings.append(f"Could not read saved trip {folder.name}: {type(exc).__name__}. Its files were kept.")
        return sorted(entries, key=lambda entry: entry["updated_at"], reverse=True)
