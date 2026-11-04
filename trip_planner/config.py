"""Environment configuration, loaded explicitly rather than during imports."""

from dataclasses import dataclass, field
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """The local configuration is not ready for the requested operation."""


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    default_model: str = ""
    extractor_model: str = ""
    planner_model: str = ""
    output_dir: Path = Path("output")
    timezone: str = "UTC"
    timeout: float = 90.0
    max_retries: int = 1

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Config":
        # Existing environment variables take precedence over an optional local file.
        load_dotenv(dotenv_path=env_file or Path.cwd() / ".env", override=False)
        model = os.getenv("OPENAI_MODEL", "").strip()
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            default_model=model,
            extractor_model=os.getenv("OPENAI_EXTRACTOR_MODEL", "").strip() or model,
            planner_model=os.getenv("OPENAI_PLANNER_MODEL", "").strip() or model,
            output_dir=Path(os.getenv("TRIP_PLANNER_OUTPUT_DIR", "output")).expanduser(),
            timezone=os.getenv("TRIP_PLANNER_TIMEZONE", "UTC").strip() or "UTC",
        )

    def validate_live(self, role: str | None = None) -> None:
        """Validate locally; never make a paid request merely to check setup."""
        missing = []
        if not self.api_key:
            missing.append("OPENAI_API_KEY")
        if role in (None, "interpreter") and not self.extractor_model:
            missing.append("OPENAI_MODEL or OPENAI_EXTRACTOR_MODEL")
        if role in (None, "planner") and not self.planner_model:
            missing.append("OPENAI_MODEL or OPENAI_PLANNER_MODEL")
        if missing:
            raise ConfigurationError(
                "Set " + ", ".join(missing) + " in your environment or .env file. "
                "You can view the offline example with: python -m trip_planner demo --no-open"
            )
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(
                "Set TRIP_PLANNER_TIMEZONE to an IANA timezone, for example Asia/Bangkok or UTC."
            ) from exc
