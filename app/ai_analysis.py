"""Strict boundary between source reports and the model input."""
import json
import math
from typing import Iterator

import httpx
from fastapi import Request
from pydantic import BaseModel

from app.security_data import HolderDistribution, LiquiditySecurity
from app.source_data import NormalizedSourceData

PROMPT_VERSION = "tai-20-v1"
MAX_INPUT_BYTES = 16_384
TIMEOUT_SECONDS = 15.0
MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = (
    "Prompt version: " + PROMPT_VERSION + ". Analyze only the supplied normalized "
    "Solana token facts. Cite sourceId and field for each conclusion. Missing facts "
    "are unknown, never evidence of safety. Do not invent data. Reply in Polish. "
    "This is informational analysis, not investment advice."
)
SOURCES = {"rugcheck", "dexscreener", "dextools", "gmgn"}
FLAG_CODES = {
    "mint_authority", "freeze_authority", "mutable_metadata", "transfer_fee",
    "top_holders_concentration", "lp_lock_status", "rugged", "dex_liquidity_depth",
    "dextools_open_source", "dextools_honeypot", "dextools_blacklist",
    "dextools_scam_warning", "gmgn_honeypot", "gmgn_lp_burn", "gmgn_bundler_rate",
}
FIELDS = {
    "price": {"price_usd", "price_native_sol"},
    "liquidity": set(LiquiditySecurity.model_fields) - {"pools"},
    "holders": set(HolderDistribution.model_fields) - {
        "top_holders", "top_holder_address", "creator_address", "owner_address"},
    "flags": {f"{source}:{code}" for source in SOURCES for code in FLAG_CODES},
}


class AIAnalysisResult(BaseModel):
    status: str
    prompt_version: str = PROMPT_VERSION
    analysis: str | None = None


def build_messages(data: NormalizedSourceData) -> list[dict[str, str]] | None:
    facts = []
    for group, allowed in FIELDS.items():
        for field, item in sorted(getattr(data, group).items()):
            # No arbitrary text, URLs, record dictionaries or provider metadata.
            value = item.value
            if field not in allowed or item.sourceId not in SOURCES:
                continue
            if type(value) not in (int, float, bool):
                continue
            if type(value) is float and not math.isfinite(value):
                continue
            facts.append({"field": f"{group}.{field}", "value": value,
                          "sourceId": item.sourceId})
    if not facts:
        return None
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"facts": facts}, allow_nan=False)}]
    if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("AI_INPUT_TOO_LARGE")
    return messages


class AIAnalysisClient:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, client: httpx.Client, api_key: str | None):
        self.client = client
        self.api_key = api_key

    def analyse(self, data: NormalizedSourceData) -> AIAnalysisResult:
        try:
            messages = build_messages(data)
        except ValueError:
            return AIAnalysisResult(status="input_too_large")
        if messages is None:
            return AIAnalysisResult(status="no_data")
        if not self.api_key:
            return AIAnalysisResult(status="not_configured")
        try:
            response = self.client.post(
                self.URL, headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": MODEL, "messages": messages, "max_tokens": 1000},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty analysis")
        except httpx.TimeoutException:
            return AIAnalysisResult(status="timeout")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return AIAnalysisResult(status="unavailable")
        return AIAnalysisResult(status="completed", analysis=content)


def get_ai_client(request: Request) -> Iterator[AIAnalysisClient]:
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        yield AIAnalysisClient(client, request.app.state.settings.ai_api_key)
