"""Strict boundary between source reports and the model input."""
from datetime import datetime, timezone
import json
import math
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

import httpx
from fastapi import Request
from pydantic import BaseModel, Field

from app.security_data import HolderDistribution, LiquiditySecurity
from app.source_data import NormalizedSourceData

PROMPT_VERSION = "tai-20-v1"
MAX_INPUT_BYTES = 16_384
TIMEOUT_SECONDS = 15.0
MIN_SCORE = 0
MAX_SCORE = 100
MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = (
    "Prompt version: " + PROMPT_VERSION + ". Analyze only the supplied normalized "
    "Solana token facts. Cite sourceId and field for each conclusion. Missing facts "
    "are unknown, never evidence of safety. Do not invent data. Reply in Polish as "
    'strict JSON: {"score": 0..100, "summary": "...", "fact_ids": ["..."]}. '
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


class AIOutputValidationError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class ValidatedAIOutput(BaseModel):
    score: float | int
    summary: str
    fact_ids: list[str]


class AIAnalysisResult(BaseModel):
    id: str | None = None
    address: str | None = None
    status: str
    prompt_version: str = PROMPT_VERSION
    analysis: str | None = None
    summary: str | None = None
    score: float | int | None = None
    fact_ids: list[str] = Field(default_factory=list)
    analysed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    rejected: bool = False
    reason: str | None = None


class AIAnalysisStore:
    """Persistence store for validated AI analysis results with prompt version and timestamp."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_analyses (
                id TEXT PRIMARY KEY,
                address TEXT,
                prompt_version TEXT NOT NULL,
                analysed_at TEXT NOT NULL,
                score REAL NOT NULL,
                fact_ids_json TEXT NOT NULL,
                analysis TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        self._records: list[AIAnalysisResult] = []

    def save(self, result: AIAnalysisResult) -> AIAnalysisResult:
        if result.status != "completed" or result.rejected or result.analysed_at is None:
            raise ValueError("Only validated completed AI results may be saved")
        self._conn.execute(
            """
            INSERT INTO ai_analyses (id, address, prompt_version, analysed_at, score, fact_ids_json, analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.id or str(uuid4()),
                result.address,
                result.prompt_version,
                result.analysed_at.isoformat(),
                float(result.score) if result.score is not None else 0.0,
                json.dumps(result.fact_ids, ensure_ascii=False),
                result.analysis or "",
            ),
        )
        self._conn.commit()
        self._records.append(result)
        return result

    def all(self) -> list[AIAnalysisResult]:
        return list(self._records)

    def list_for_address(self, address: str) -> list[AIAnalysisResult]:
        return [item for item in self._records if item.address == address]

    def get_latest(self, address: str | None = None) -> AIAnalysisResult | None:
        if address is None:
            return self._records[-1] if self._records else None
        matching = self.list_for_address(address)
        return matching[-1] if matching else None

    def __len__(self) -> int:
        return len(self._records)


def extract_valid_facts(
    data: NormalizedSourceData,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    facts: list[dict[str, Any]] = []
    allowed_fact_ids: dict[str, str] = {}
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
            canonical_id = f"{group}.{field}"
            facts.append({
                "field": canonical_id,
                "value": value,
                "sourceId": item.sourceId,
            })
            allowed_fact_ids[canonical_id] = canonical_id
            allowed_fact_ids[f"{item.sourceId}:{canonical_id}"] = canonical_id
            allowed_fact_ids[f"{item.sourceId}.{canonical_id}"] = canonical_id
            if group == "flags":
                allowed_fact_ids[field] = canonical_id
    return facts, allowed_fact_ids


def build_messages(data: NormalizedSourceData) -> list[dict[str, str]] | None:
    facts, _ = extract_valid_facts(data)
    if not facts:
        return None
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"facts": facts}, allow_nan=False)}]
    if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("AI_INPUT_TOO_LARGE")
    return messages


def _reject_non_finite_constant(constant: str) -> Any:
    raise AIOutputValidationError("invalid_json", f"Invalid JSON constant: {constant}")


def validate_model_output(
    content: object,
    allowed_fact_ids: dict[str, str],
) -> ValidatedAIOutput:
    if not isinstance(content, str) or not content.strip():
        raise AIOutputValidationError("invalid_json", "Model output is empty or not a string")

    try:
        payload = json.loads(content, parse_constant=_reject_non_finite_constant)
    except AIOutputValidationError:
        raise
    except (ValueError, TypeError) as error:
        raise AIOutputValidationError("invalid_json", "Model output is not valid JSON") from error

    if not isinstance(payload, dict):
        raise AIOutputValidationError("invalid_json", "Model output must be a JSON object")

    # 1. Validate score presence, numeric type (excluding bool) and range [0, 100]
    raw_score = payload.get("score") if "score" in payload else payload.get("risk_score")
    if type(raw_score) not in (int, float) or not math.isfinite(raw_score):
        raise AIOutputValidationError(
            "invalid_score_range", "Score must be a finite number"
        )
    if raw_score < MIN_SCORE or raw_score > MAX_SCORE:
        raise AIOutputValidationError(
            "invalid_score_range",
            f"Score {raw_score} is outside the valid range [{MIN_SCORE}, {MAX_SCORE}]",
        )

    # 2. Validate factId references against supplied facts for this analysis
    raw_fact_ids: list[Any] = []
    has_fact_container = False

    for list_key in ("fact_ids", "factIds"):
        if list_key in payload:
            has_fact_container = True
            container = payload[list_key]
            if not isinstance(container, list) or not container:
                raise AIOutputValidationError(
                    "invalid_fact_id", f"{list_key} must be a non-empty list"
                )
            raw_fact_ids.extend(container)

    for single_key in ("factId", "fact_id"):
        if single_key in payload:
            has_fact_container = True
            raw_fact_ids.append(payload[single_key])

    for reasons_key in ("reasons", "conclusions", "findings"):
        if reasons_key in payload:
            reasons_val = payload[reasons_key]
            if not isinstance(reasons_val, list):
                raise AIOutputValidationError(
                    "invalid_schema", f"{reasons_key} must be a list"
                )
            for item in reasons_val:
                if not isinstance(item, dict):
                    raise AIOutputValidationError(
                        "invalid_schema", f"Items in {reasons_key} must be objects"
                    )
                for fk in ("factId", "fact_id"):
                    if fk in item:
                        has_fact_container = True
                        raw_fact_ids.append(item[fk])
                for flk in ("factIds", "fact_ids"):
                    if flk in item:
                        has_fact_container = True
                        if not isinstance(item[flk], list) or not item[flk]:
                            raise AIOutputValidationError(
                                "invalid_fact_id", f"{flk} must be a non-empty list"
                            )
                        raw_fact_ids.extend(item[flk])

    if not has_fact_container or not raw_fact_ids:
        raise AIOutputValidationError(
            "invalid_fact_id", "Model output must reference at least one valid factId"
        )

    normalized_fact_ids: list[str] = []
    for candidate in raw_fact_ids:
        if not isinstance(candidate, str) or not candidate.strip():
            raise AIOutputValidationError(
                "invalid_fact_id", "Every factId must be a non-empty string"
            )
        stripped = candidate.strip()
        canonical = allowed_fact_ids.get(stripped)
        if canonical is None:
            raise AIOutputValidationError(
                "invalid_fact_id",
                f"FactId '{stripped}' is not present in the supplied token facts",
            )
        if canonical not in normalized_fact_ids:
            normalized_fact_ids.append(canonical)

    # 3. Validate summary / analysis text
    raw_summary = (
        payload.get("summary")
        if "summary" in payload
        else payload.get("analysis")
    )
    if not isinstance(raw_summary, str) or not raw_summary.strip():
        raise AIOutputValidationError(
            "invalid_schema", "Model output must include a non-empty summary/analysis string"
        )

    return ValidatedAIOutput(
        score=raw_score,
        summary=raw_summary.strip(),
        fact_ids=normalized_fact_ids,
    )


class AIAnalysisClient:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        client: httpx.Client,
        api_key: str | None,
        *,
        store: AIAnalysisStore | None = None,
    ):
        self.client = client
        self.api_key = api_key
        self.store = store if store is not None else AIAnalysisStore()

    @property
    def saved_analyses(self) -> list[AIAnalysisResult]:
        return self.store.all()

    def analyse(
        self,
        data: NormalizedSourceData,
        *,
        address: str | None = None,
    ) -> AIAnalysisResult:
        try:
            messages = build_messages(data)
        except ValueError:
            return AIAnalysisResult(status="input_too_large")
        if messages is None:
            return AIAnalysisResult(status="no_data")
        if not self.api_key:
            return AIAnalysisResult(status="not_configured")

        _, allowed_fact_ids = extract_valid_facts(data)
        try:
            response = self.client.post(
                self.URL, headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": MODEL, "messages": messages, "max_tokens": 1000},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            return AIAnalysisResult(status="timeout")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return AIAnalysisResult(status="unavailable")

        try:
            validated = validate_model_output(content, allowed_fact_ids)
        except AIOutputValidationError as error:
            return AIAnalysisResult(
                address=address,
                status="unavailable",
                prompt_version=PROMPT_VERSION,
                analysis=None,
                summary=None,
                score=None,
                fact_ids=[],
                rejected=True,
                reason=error.reason,
            )

        analysed_at = datetime.now(timezone.utc)
        result = AIAnalysisResult(
            id=str(uuid4()),
            address=address,
            status="completed",
            prompt_version=PROMPT_VERSION,
            analysis=validated.summary,
            summary=validated.summary,
            score=validated.score,
            fact_ids=validated.fact_ids,
            analysed_at=analysed_at,
            created_at=analysed_at,
            updated_at=analysed_at,
            rejected=False,
            reason=None,
        )
        self.store.save(result)
        return result


_DEFAULT_AI_STORE = AIAnalysisStore()


def get_ai_client(request: Request) -> Iterator[AIAnalysisClient]:
    store = getattr(request.app.state, "ai_store", _DEFAULT_AI_STORE)
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        yield AIAnalysisClient(client, request.app.state.settings.ai_api_key, store=store)
