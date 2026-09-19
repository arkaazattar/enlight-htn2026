"""Pure Gemini API client — makes the call, parses the result, nothing else.

Authentication: set GEMINI_API_KEY in your .env file.
Model: set GEMINI_MODEL env var (default: gemini-2.5-flash).
Prompt: edit llm/prompts.py.

This module has NO threading, NO corroboration logic, NO state.
See coordinator.py for trigger logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from .prompts import IDENTITY_ANALYSIS_PROMPT


class AnalyzerError(Exception):
    """Gemini API call or response parsing failed."""


@dataclass
class Proposal:
    """What Gemini extracted for one person from a batch of speech turns."""
    person_id: str
    name: str | None        # None = Gemini found no name yet
    facts: list[str]        # Simple plain-text fact strings


# JSON schema sent to Gemini for structured output
_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "person_id": {"type": "string"},
                    "name": {"type": "string", "nullable": True},
                    "facts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["person_id", "name", "facts"],
            },
        }
    },
    "required": ["proposals"],
}


class GeminiAnalyzer:
    """Calls Gemini and returns a list of Proposals — pure API, no side effects."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        if not api_key:
            raise AnalyzerError(
                "GEMINI_API_KEY is not set. Add it to your .env:\n  GEMINI_API_KEY=your-key-here"
            )
        try:
            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=20_000),
            )
        except Exception as exc:
            raise AnalyzerError(f"Could not initialize Gemini client: {exc}") from exc
        self._model = model

    def analyze(
        self,
        turns: list,                         # list[SpeechTurn]
        participants: dict[str, str | None],  # {person_id: name|None}
    ) -> list[Proposal]:
        """Send turns to Gemini and return parsed Proposals.

        Raises AnalyzerError on failure (caller decides whether to retry).
        """
        payload = {
            "participants": participants,
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "person_id": t.person_id,
                    "text": t.text,
                    "speaker_id": t.speaker_id,
                }
                for t in turns
            ],
        }

        # Try configured model, fallback to alternative flash models on 503 spikes
        models_to_try = [self._model]
        for fallback in ("gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"):
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_err = None
        data = None
        for m in models_to_try:
            try:
                response = self._client.models.generate_content(
                    model=m,
                    contents=json.dumps(payload, ensure_ascii=False),
                    config=types.GenerateContentConfig(
                        system_instruction=IDENTITY_ANALYSIS_PROMPT,
                        response_mime_type="application/json",
                        response_schema=_SCHEMA,
                    ),
                )
                data = json.loads(response.text)
                break
            except Exception as exc:
                last_err = exc
                continue

        if data is None:
            raise AnalyzerError(f"Gemini call failed: {last_err}") from last_err

        proposals = data.get("proposals")
        if not isinstance(proposals, list):
            raise AnalyzerError("Gemini returned unexpected response format.")

        result: list[Proposal] = []
        for item in proposals:
            pid = item.get("person_id", "")
            if pid not in participants:
                continue  # ignore unknown IDs hallucinated by Gemini
            name = item.get("name")
            if isinstance(name, str):
                name = name.strip() or None
            facts = [f.strip() for f in item.get("facts", []) if isinstance(f, str) and f.strip()]
            result.append(Proposal(person_id=pid, name=name, facts=facts))
        return result

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
