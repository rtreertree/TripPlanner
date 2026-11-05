"""Environment configuration, loaded explicitly rather than during imports."""

from dataclasses import dataclass, field
import math
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
    max_retries: int = 0
    request_deadline: float = 300.0
    extractor_max_output_tokens: int = 2000
    planner_max_output_tokens: int = 6000
    reasoning_effort: str | None = "low"
    planner_workers: int = 3

    def __post_init__(self):
        for name, setting in (("timeout", "OPENAI_TIMEOUT_SECONDS"),
                              ("request_deadline", "OPENAI_REQUEST_DEADLINE_SECONDS")):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ConfigurationError(f"{setting} must be a positive, finite number of seconds.")
        if not 0 <= self.max_retries <= 3:
            raise ConfigurationError("OPENAI_MAX_RETRIES must be an integer from 0 to 3.")
        if self.reasoning_effort not in {None, "none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ConfigurationError("OPENAI_REASONING_EFFORT must be default, none, minimal, low, medium, high, xhigh, or max.")
        if not isinstance(self.planner_workers, int) or not 1 <= self.planner_workers <= 4:
            raise ConfigurationError("TRIP_PLANNER_WORKERS must be an integer from 1 to 4.")
        for name, setting in (("extractor_max_output_tokens", "OPENAI_EXTRACTOR_MAX_OUTPUT_TOKENS"),
                              ("planner_max_output_tokens", "OPENAI_PLANNER_MAX_OUTPUT_TOKENS")):
            if getattr(self, name) < 1:
                raise ConfigurationError(f"{setting} must be a positive integer.")

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Config":
        # Existing environment variables take precedence over an optional local file.
        load_dotenv(dotenv_path=env_file or Path.cwd() / ".env", override=False)
        model = os.getenv("OPENAI_MODEL", "").strip()
        effort = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower()

        def number(name, default, convert):
            try:
                return convert(os.getenv(name, str(default)))
            except ValueError:
                raise ConfigurationError(f"{name} must be a valid {'integer' if convert is int else 'number'}.") from None

        return cls(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            default_model=model,
            extractor_model=os.getenv("OPENAI_EXTRACTOR_MODEL", "").strip() or model,
            planner_model=os.getenv("OPENAI_PLANNER_MODEL", "").strip() or model,
            output_dir=Path(os.getenv("TRIP_PLANNER_OUTPUT_DIR", "output")).expanduser(),
            timezone=os.getenv("TRIP_PLANNER_TIMEZONE", "UTC").strip() or "UTC",
            timeout=number("OPENAI_TIMEOUT_SECONDS", 90, float),
            max_retries=number("OPENAI_MAX_RETRIES", 0, int),
            request_deadline=number("OPENAI_REQUEST_DEADLINE_SECONDS", 300, float),
            extractor_max_output_tokens=number("OPENAI_EXTRACTOR_MAX_OUTPUT_TOKENS", 2000, int),
            planner_max_output_tokens=number("OPENAI_PLANNER_MAX_OUTPUT_TOKENS", 6000, int),
            reasoning_effort=effort if effort not in {"", "default"} else None,
            planner_workers=number("TRIP_PLANNER_WORKERS", 3, int),
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
