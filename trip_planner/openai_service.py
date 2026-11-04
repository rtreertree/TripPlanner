"""One small synchronous boundary around the official Responses API."""

from datetime import datetime, timezone
import json
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
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
    return json.dumps(value, ensure_ascii=False, default=str)


class OpenAIService:
    def __init__(self, config: Config, client: Any = None):
        self.config = config
        self._client = client
        self.last_metadata: RoleGeneration | None = None

    def parse(self, *, role: str, prompt: str, data: dict, response_model: type[Result]) -> Result:
        self.last_metadata = None
        self.config.validate_live(role)
        model = self.config.extractor_model if role == "interpreter" else self.config.planner_model
        if self._client is None:
            # The SDK alone retries transient errors once. Callers offer explicit
            # Retry to the user; there is no additional automatic network retry loop.
            self._client = OpenAI(
                api_key=self.config.api_key,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )
        try:
            response = self._client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json_data(data)},
                ],
                text_format=response_model,
                store=False,
            )
        except AuthenticationError as exc:
            raise AIServiceError("OpenAI authentication failed. Check OPENAI_API_KEY, then retry.") from exc
        except PermissionDeniedError as exc:
            raise AIServiceError("OpenAI access was denied. Check the key's project and model permissions.") from exc
        except NotFoundError as exc:
            raise AIServiceError("The configured OpenAI model is unavailable. Check the model name and account access.") from exc
        except RateLimitError as exc:
            raise AIServiceError("OpenAI rate or quota limit reached. Check your usage and billing, then retry later.") from exc
        except APITimeoutError as exc:
            raise AIServiceError("The OpenAI request timed out. Your saved work is unchanged; retry when ready.") from exc
        except APIConnectionError as exc:
            raise AIServiceError("Could not connect to OpenAI. Check your connection, then retry.") from exc
        except BadRequestError as exc:
            raise AIServiceError("OpenAI could not accept the request. Use a model that supports Responses Structured Outputs.") from exc
        except APIStatusError as exc:
            raise AIServiceError("OpenAI could not complete the request. Your saved work is unchanged; retry later.") from exc
        except (ValidationError, json.JSONDecodeError) as exc:
            raise AIServiceError("OpenAI returned an invalid structured response. Your saved work is unchanged; retry.") from exc

        for output in response.output or []:
            for content in getattr(output, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    raise AIServiceError("OpenAI declined this request. Rephrase your trip request and try again.")
        if response.status != "completed":
            raise AIServiceError("OpenAI returned an incomplete response. Your saved work is unchanged; retry.")
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
            usage=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            ) if usage else None,
        )
        return result
