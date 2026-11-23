"""Strict boundary between source reports and the model input."""
from datetime import datetime, timezone
import json
import logging
import math
import sqlite3
from typing import Any, Callable, Iterator
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.ai_report import AIMetric, METRICS, REPORT_PROMPT_VERSION, detailed_messages, report_facts
from app.security_data import HolderDistribution, LiquiditySecurity
from app.source_data import NormalizedSourceData

PROMPT_VERSION = "tai-20-v1"
MAX_INPUT_BYTES = 16_384
TIMEOUT_SECONDS = 15.0
OPENROUTER_TIMEOUT_SECONDS = 40.0
MIN_SCORE = 0
MAX_SCORE = 100
MODEL = "gpt-4o-mini"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "inclusionai/ling-3.2-flash:free"
BAZAARLINK_URL = "https://api.bazaarlink.ai/v1/chat/completions"
BAZAARLINK_MODEL = "deepseek/deepseek-v4-flash-0731free"
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


OPENROUTER_OPTIONS = {
    "reasoning": {"enabled": False},
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "token_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "score": {"type": "number"},
                    "summary": {"type": "string"},
                    "fact_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["score", "summary", "fact_ids"],
                "additionalProperties": False,
            },
        },
    },
}


def output_schema(deep: bool) -> dict:
    schema = OPENROUTER_OPTIONS["response_format"]["json_schema"]["schema"]
    if not deep:
        return schema
    return {
        **schema,
        "properties": {**schema["properties"], "metrics": {"type": "array", "items": {
            "type": "object", "properties": {
                "key": {"type": "string", "enum": list(METRICS)},
                "score": {"type": ["number", "null"]},
                "rationale": {"type": "string"},
                "fact_ids": {"type": "array", "items": {"type": "string"}},
            }, "required": ["key", "score", "rationale", "fact_ids"], "additionalProperties": False,
        }}},
        "required": [*schema["required"], "metrics"],
    }


def copilot_report_schema(fact_count: int) -> dict:
    fact_ids = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": fact_count}}
    metric = {
        "type": "object", "additionalProperties": False, "required": ["score", "rationale", "fact_ids"],
        "properties": {"score": {"type": ["number", "null"]}, "rationale": {"type": "string"},
                       "fact_ids": fact_ids},
    }
    schema = output_schema(False)
    return {**schema, "required": [*schema["required"], "metrics"], "properties": {
        **schema["properties"], "fact_ids": {**fact_ids, "minItems": 1},
        "metrics": {"type": "object", "additionalProperties": False, "required": list(METRICS),
                    "properties": dict.fromkeys(METRICS, metric)},
    }}


def decode_copilot_report(content: str, fact_paths: tuple[str, ...]) -> str:
    try:
        report = json.loads(content, parse_constant=_reject_non_finite_constant)
    except (TypeError, ValueError) as error:
        raise AIOutputValidationError("invalid_json", "Expected a structured Copilot report") from error
    if not isinstance(report, dict):
        raise AIOutputValidationError("invalid_json", "Expected a structured Copilot report")

    def decode_ids(ids):
        if not isinstance(ids, list) or any(type(index) is not int or not 1 <= index <= len(fact_paths) for index in ids):
            raise AIOutputValidationError("invalid_fact_id", "Copilot cited an unknown evidence number")
        return [fact_paths[index - 1] for index in ids]

    metrics = report.get("metrics")
    if (not isinstance(metrics, dict) or metrics.keys() != METRICS.keys()
            or any(not isinstance(value, dict) or value.keys() != {"score", "rationale", "fact_ids"}
                   for value in metrics.values())):
        raise AIOutputValidationError("invalid_metrics", "Expected one complete assessment for each dimension")
    report["fact_ids"] = decode_ids(report.get("fact_ids"))
    report["metrics"] = [{**metric, "key": key, "fact_ids": decode_ids(metric["fact_ids"])}
                         for key, metric in metrics.items()]
    return json.dumps(report, ensure_ascii=False)


class AIAnalysisResult(BaseModel):
    id: str | None = None
    address: str | None = None
    status: str
    prompt_version: str = PROMPT_VERSION
    analysis: str | None = None
    summary: str | None = None
    score: float | int | None = None
    fact_ids: list[str] = Field(default_factory=list)
    metrics: list[AIMetric] = Field(default_factory=list)
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
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(ai_analyses)")}
        if "metrics_json" not in columns:
            self._conn.execute("ALTER TABLE ai_analyses ADD COLUMN metrics_json TEXT NOT NULL DEFAULT '[]'")
            self._conn.commit()
        self._records: list[AIAnalysisResult] = []

    def save(self, result: AIAnalysisResult) -> AIAnalysisResult:
        if result.status != "completed" or result.rejected or result.analysed_at is None:
            raise ValueError("Only validated completed AI results may be saved")
        self._conn.execute(
            """
            INSERT INTO ai_analyses (id, address, prompt_version, analysed_at, score, fact_ids_json, analysis, metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.id or str(uuid4()),
                result.address,
                result.prompt_version,
                result.analysed_at.isoformat(),
                float(result.score) if result.score is not None else 0.0,
                json.dumps(result.fact_ids, ensure_ascii=False),
                result.analysis or "",
                json.dumps([metric.model_dump() for metric in result.metrics], ensure_ascii=False),
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
        openrouter_api_key: str | None = None,
        bazaarlink_api_key: str | None = None,
        completion: Callable[[list[dict], dict], str] | None = None,
    ):
        self.client = client
        self.api_key = api_key
        self.openrouter_api_key = openrouter_api_key
        self.bazaarlink_api_key = bazaarlink_api_key
        self.completion = completion
        self.store = store if store is not None else AIAnalysisStore()

    @property
    def saved_analyses(self) -> list[AIAnalysisResult]:
        return self.store.all()

    def analyse_report(self, snapshot: dict, *, address: str) -> AIAnalysisResult:
        facts = report_facts(snapshot)
        if not any(isinstance(value, (int, float, bool)) or
                   (isinstance(value, dict) and isinstance(value.get("value"), (int, float, bool)))
                   for key,value in facts.items()
                   if key.startswith(("market_data.", "gmgn_activity.", "onchain_data.",
                                      "security_data.", "listing.", "local_research."))
                   and key.rsplit(".",1)[-1] not in {
                       "http_status","read_only","slot","pages_fetched","page","page_size","max_pages",
                       "sample_size","top_10_count","sample_accounts","mint_slot","holders_slot",
                       "critical_flags_count","warning_flags_count","safe_flags_count","total_flags_count",
                   }):
            return AIAnalysisResult(status="no_data", prompt_version=REPORT_PROMPT_VERSION)
        copilot = self.completion is not None
        messages = detailed_messages(facts, copilot=copilot)
        if len(messages[1]["content"].encode()) > 128_000:
            return AIAnalysisResult(status="input_too_large", prompt_version=REPORT_PROMPT_VERSION)
        return self._analyse_messages(messages, {path: path for path in facts}, address, deep=True)

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
        _, allowed_fact_ids = extract_valid_facts(data)
        return self._analyse_messages(messages, allowed_fact_ids, address)

    def _analyse_messages(self, messages, allowed_fact_ids, address, *, deep=False):
        version = REPORT_PROMPT_VERSION if deep else PROMPT_VERSION
        if self.completion is not None:
            try:
                schema = copilot_report_schema(len(allowed_fact_ids)) if deep else output_schema(False)
                content = self.completion(messages, schema)
            except TimeoutError as error:
                return AIAnalysisResult(status="timeout", reason=getattr(error, "reason", None), prompt_version=version)
            except Exception:
                # Runtime exceptions can contain sensitive upstream diagnostics.
                return AIAnalysisResult(status="unavailable", reason="copilot_unavailable", prompt_version=version)
            return self._validate_and_save(content, allowed_fact_ids, address, version, deep)
        api_key = self.bazaarlink_api_key or self.openrouter_api_key or self.api_key
        if not api_key:
            return AIAnalysisResult(status="not_configured", prompt_version=version)

        use_bazaarlink = bool(self.bazaarlink_api_key)
        use_openrouter = not use_bazaarlink and bool(self.openrouter_api_key)
        url, model = self.URL, MODEL
        headers = {"Authorization": f"Bearer {api_key}"}
        if use_bazaarlink:
            url, model = BAZAARLINK_URL, BAZAARLINK_MODEL
            headers["X-Free-Fallback"] = "false"
        elif use_openrouter:
            url, model = OPENROUTER_URL, OPENROUTER_MODEL
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": 4100 if deep else 1000,
        }
        if use_openrouter:
            body.update(OPENROUTER_OPTIONS)
        if use_bazaarlink:
            body["response_format"] = {"type": "json_object"}
            body["include_reasoning"] = False
        elif deep:
            body["response_format"] = {"type":"json_schema", "json_schema":{
                "name":"deep_token_analysis","strict":True,"schema":output_schema(deep),
            }}
        try:
            response = self.client.post(
                url,
                headers=headers,
                json=body,
                timeout=75.0 if deep else OPENROUTER_TIMEOUT_SECONDS if (use_openrouter or use_bazaarlink) else TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            return AIAnalysisResult(status="timeout", prompt_version=version)
        except httpx.HTTPStatusError as error:
            if use_bazaarlink:
                reason = {
                    401: "bazaarlink_invalid_api_key",
                    402: "bazaarlink_insufficient_credits",
                    429: "bazaarlink_rate_limited",
                }.get(error.response.status_code)
                return AIAnalysisResult(status="unavailable", reason=reason, prompt_version=version)
            reason = {401: "invalid_api_key", 429: "rate_limited"}.get(error.response.status_code)
            return AIAnalysisResult(status="unavailable", reason=reason if use_openrouter else None, prompt_version=version)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return AIAnalysisResult(status="unavailable", prompt_version=version)

        return self._validate_and_save(content, allowed_fact_ids, address, version, deep)

    def _validate_and_save(self, content, allowed_fact_ids, address, version, deep):
        try:
            if deep and self.completion is not None:
                content = decode_copilot_report(content, tuple(allowed_fact_ids))
            validated = validate_model_output(content, allowed_fact_ids)
            metrics = self._validate_metrics(content, allowed_fact_ids) if deep else []
        except AIOutputValidationError as error:
            if self.completion is not None:
                logging.getLogger("uvicorn.error").warning("Copilot report rejected reason=%s", error.reason)
            return AIAnalysisResult(
                address=address,
                status="unavailable",
                prompt_version=version,
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
            prompt_version=version,
            analysis=validated.summary,
            summary=validated.summary,
            score=validated.score,
            fact_ids=validated.fact_ids,
            metrics=metrics,
            analysed_at=analysed_at,
            created_at=analysed_at,
            updated_at=analysed_at,
            rejected=False,
            reason=None,
        )
        self.store.save(result)
        return result

    @staticmethod
    def _validate_metrics(content: str, allowed_fact_ids: dict) -> list[AIMetric]:
        raw_metrics = json.loads(content).get("metrics")
        if not isinstance(raw_metrics, list) or len(raw_metrics) != len(METRICS):
            raise AIOutputValidationError("invalid_metrics", "Expected one result per report metric")
        try:
            metrics = [AIMetric.model_validate(item) for item in raw_metrics]
        except ValueError as error:
            raise AIOutputValidationError("invalid_metrics", "Invalid metric score or rationale") from error
        by_key = {metric.key:metric for metric in metrics}
        if set(by_key) != set(METRICS) or not any(metric.score is not None for metric in metrics):
            raise AIOutputValidationError("invalid_metrics", "Missing metric keys or supported scores")
        for metric in metrics:
            if not metric.rationale.strip() or (metric.score is not None and not metric.fact_ids):
                raise AIOutputValidationError("invalid_metrics", "Scored metrics require evidence and rationale")
            if any(fact_id not in allowed_fact_ids for fact_id in metric.fact_ids):
                raise AIOutputValidationError("invalid_fact_id", "Metric references an unknown fact")
        return [by_key[key] for key in METRICS]


_DEFAULT_AI_STORE = AIAnalysisStore()


def get_ai_client(request: Request, response: Response) -> Iterator[AIAnalysisClient]:
    store = getattr(request.app.state, "ai_store", _DEFAULT_AI_STORE)
    settings = request.app.state.settings
    if settings.ai_provider == "github_copilot":
        from functools import partial
        from app import copilot_analysis, github_auth

        response.headers.update(github_auth.PRIVATE_HEADERS)
        if request.method == "POST":
            github_auth.require_origin(request)
        if not github_auth.configured(settings):
            raise HTTPException(503, "GITHUB_OAUTH_NOT_CONFIGURED", headers=github_auth.PRIVATE_HEADERS)
        session = github_auth.current_session(request)
        if session is None:
            raise HTTPException(401, "GITHUB_SIGN_IN_REQUIRED", headers=github_auth.PRIVATE_HEADERS)
        generating = request.method == "POST"
        if generating and not session.inference_lock.acquire(blocking=False):
            raise HTTPException(409, "COPILOT_ANALYSIS_IN_PROGRESS", headers=github_auth.PRIVATE_HEADERS)
        try:
            with httpx.Client() as client:
                yield AIAnalysisClient(client, None, store=session.store,
                                       completion=partial(copilot_analysis.complete, session.token))
        finally:
            if generating:
                session.inference_lock.release()
        return
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        yield AIAnalysisClient(client, settings.ai_api_key, store=store,
                               openrouter_api_key=settings.openrouter_api_key,
                               bazaarlink_api_key=settings.bazaarlink_api_key)
