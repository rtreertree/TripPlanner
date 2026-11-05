"""One small synchronous boundary around the official Responses API."""

from datetime import datetime, timezone
import json
from time import monotonic
from threading import Lock, local
from typing import Any, Callable, TypeVar

import httpx

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from .config import Config
from .models import RoleGeneration, TokenUsage


class AIServiceError(RuntimeError):
    """A safe, user-facing error; provider messages and credentials are excluded."""


Result = TypeVar("Result", bound=BaseModel)


def json_data(value: Any) -> str:
    """Keep untrusted trip text in a single JSON data message."""
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


class OpenAIService:
    def __init__(self, config: Config, client: Any = None):
        self.config = config
        self._client = client
        self._client_lock = Lock()
        self._metadata = local()
        self.last_metadata: RoleGeneration | None = None

    @property
    def last_metadata(self) -> RoleGeneration | None:
        return getattr(self._metadata, "value", None)

    @last_metadata.setter
    def last_metadata(self, value):
        self._metadata.value = value

    def _get_client(self):
        # The SDK's HTTP client is shared; initialization and per-call metadata
        # must not race when several day requests start at the same time.
        with self._client_lock:
            if self._client is None:
                self._client = OpenAI(
                    api_key=self.config.api_key,
                    timeout=httpx.Timeout(min(self.config.timeout, self.config.request_deadline),
                                          connect=min(10.0, self.config.timeout, self.config.request_deadline)),
                    max_retries=self.config.max_retries,
                )
            return self._client

    def parse(self, *, role: str, prompt: str, data: dict, response_model: type[Result],
              progress: Callable[[str], None] | None = None) -> Result:
        self.last_metadata = None
        self.config.validate_live(role)
        model = self.config.extractor_model if role == "interpreter" else self.config.planner_model
        client = self._get_client()
        options = {"reasoning": {"effort": self.config.reasoning_effort}} if self.config.reasoning_effort else {}
        started = last_progress = monotonic()
        try:
            # Receiving tokens keeps the read timeout from expiring during a
            # healthy generation. Only the final, validated result is returned.
            with client.responses.stream(
                model=model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json_data(data)},
                ],
                text_format=response_model,
                store=False,
                max_output_tokens=(self.config.extractor_max_output_tokens if role == "interpreter"
                                   else self.config.planner_max_output_tokens),
                **options,
            ) as stream:
                for event in stream:
                    now = monotonic()
                    if now - started >= self.config.request_deadline:
                        raise AIServiceError("This planning step exceeded its time limit. Completed days are saved; Retry resumes the unfinished step.")
                    if event.type in {"response.failed", "error"}:
                        raise AIServiceError("OpenAI could not complete this step. Completed work is saved; retry later.")
                    if event.type == "response.incomplete":
                        reason = getattr(getattr(event.response, "incomplete_details", None), "reason", None)
                        raise AIServiceError(self._incomplete_message(reason, role))
                    if progress and now - last_progress >= 15:
                        progress(f"Still working on this step ({int(now - started)}s elapsed)…")
                        last_progress = now
                try:
                    response = stream.get_final_response()
                except RuntimeError as exc:
                    raise AIServiceError("The OpenAI response stream ended early. Completed work is saved; retry the unfinished step.") from exc
        except AuthenticationError as exc:
            raise AIServiceError("OpenAI authentication failed. Check OPENAI_API_KEY, then retry.") from exc
        except PermissionDeniedError as exc:
            raise AIServiceError("OpenAI access was denied. Check the key's project and model permissions.") from exc
        except NotFoundError as exc:
            raise AIServiceError("The configured OpenAI model is unavailable. Check the model name and account access.") from exc
        except RateLimitError as exc:
            raise AIServiceError("OpenAI rate or quota limit reached. Check your usage and billing, then retry later.") from exc
        except (APITimeoutError, httpx.TimeoutException) as exc:
            raise AIServiceError("OpenAI stopped responding before this step completed. Completed work is saved; Retry resumes the unfinished step. Check OPENAI_TIMEOUT_SECONDS if this keeps happening.") from exc
        except (APIConnectionError, httpx.TransportError) as exc:
            raise AIServiceError("Could not connect to OpenAI. Check your connection, then retry.") from exc
        except BadRequestError as exc:
            raise AIServiceError("OpenAI could not accept the request. Check model support for Responses Structured Outputs and OPENAI_REASONING_EFFORT; use default to omit reasoning settings.") from exc
        except APIStatusError as exc:
            raise AIServiceError("OpenAI could not complete the request. Your saved work is unchanged; retry later.") from exc
        except (ValidationError, json.JSONDecodeError) as exc:
            raise AIServiceError("OpenAI returned an invalid structured response. Your saved work is unchanged; retry.") from exc
        except AIServiceError:
            raise
        except (APIError, RuntimeError) as exc:
            raise AIServiceError("The OpenAI response stream ended unexpectedly. Completed work is saved; retry the unfinished step.") from exc

        for output in response.output or []:
            for content in getattr(output, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    raise AIServiceError("OpenAI declined this request. Rephrase your trip request and try again.")
        if response.status != "completed":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            raise AIServiceError(self._incomplete_message(reason, role))
        parsed = response.output_parsed
        if parsed is None:
            raise AIServiceError("OpenAI returned no structured result. Your saved work is unchanged; retry.")
        try:
            result = response_model.model_validate(parsed)
        except ValidationError as exc:
            raise AIServiceError("OpenAI returned an invalid structured response. Your saved work is unchanged; retry.") from exc
        usage = response.usage
        self.last_metadata = RoleGeneration(
            role=role,
            provider="openai",
            model=getattr(response, "model", None) or model,
            generated_at=datetime.now(timezone.utc).isoformat(),
            reasoning_effort=self.config.reasoning_effort,
            usage=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                reasoning_tokens=getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", None),
            ) if usage else None,
        )
        return result

    @staticmethod
    def _incomplete_message(reason, role):
        if reason == "max_output_tokens":
            setting = "OPENAI_EXTRACTOR_MAX_OUTPUT_TOKENS" if role == "interpreter" else "OPENAI_PLANNER_MAX_OUTPUT_TOKENS"
            return f"This step reached its output limit. Increase {setting}, then Retry. Completed work is saved."
        return "OpenAI returned an incomplete response. Completed work is saved; retry the unfinished step."
