"""Read-only wallet recent transactions via Solscan Pro API v2.0."""

from datetime import datetime, timezone
import re
from typing import Any, Iterator, Literal

import httpx
from fastapi import Request
from pydantic import BaseModel, Field

from app.config import Settings
from app.market_data import OptionalCount, get_dexscreener_client
from app.source_cache import SourceCache

WalletDataStatus = Literal[
    "ok",
    "no_data",
    "not_configured",
    "unauthorized",
    "rate_limited",
    "unavailable",
]

_COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
_COMPUTE_BUDGET_TYPES = {
    "setcomputeunitlimit",
    "setcomputeunitprice",
    "requestunits",
    "requestheapframe",
}
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _parse_optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _normalize_type_name(raw: str) -> str:
    cleaned = raw.strip().replace("-", "_").replace(" ", "_")
    snake = _CAMEL_BOUNDARY.sub("_", cleaned).lower()
    snake = re.sub(r"_+", "_", snake).strip("_")
    return snake or "unknown"


def _extract_tx_type(item: dict[str, Any]) -> str:
    for direct_key in ("tx_type", "activity_type", "type"):
        direct_val = item.get(direct_key)
        if isinstance(direct_val, str) and direct_val.strip():
            return _normalize_type_name(direct_val)

    instructions = item.get("parsed_instructions")
    if not isinstance(instructions, list):
        instructions = item.get("instructions")
    if not isinstance(instructions, list) or not instructions:
        return "unknown"

    meaningful_types: list[str] = []
    fallback_types: list[str] = []

    for inst in instructions:
        if not isinstance(inst, dict):
            continue
        raw_type = inst.get("type") or inst.get("instruction_type") or inst.get("name")
        if not isinstance(raw_type, str) or not raw_type.strip():
            continue
        norm_type = _normalize_type_name(raw_type)
        program = str(inst.get("program") or "").strip().lower()
        program_id = str(inst.get("program_id") or inst.get("programId") or "").strip()

        is_compute_budget = (
            program in {"compute_budget", "computebudget"}
            or program_id == _COMPUTE_BUDGET_PROGRAM_ID
            or norm_type.replace("_", "") in _COMPUTE_BUDGET_TYPES
        )
        if is_compute_budget:
            fallback_types.append(norm_type)
        else:
            meaningful_types.append(norm_type)

    candidates = meaningful_types or fallback_types
    if not candidates:
        return "unknown"

    for candidate in candidates:
        if "swap" in candidate or candidate in {"route", "shared_accounts_route"}:
            return "swap"

    return candidates[0]


def _parse_timestamp(block_time: int | None, raw_time: object) -> datetime | None:
    if block_time is not None and block_time > 0:
        return datetime.fromtimestamp(block_time, tz=timezone.utc)
    if isinstance(raw_time, str) and raw_time.strip():
        iso_candidate = raw_time.strip()
        if iso_candidate.endswith("Z"):
            iso_candidate = iso_candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(iso_candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _parse_tx_status(raw_status: object) -> Literal["success", "failed", "unknown"]:
    if isinstance(raw_status, str):
        lowered = raw_status.strip().lower()
        if lowered in {"success", "ok", "succeeded", "finalized", "confirmed"}:
            return "success"
        if lowered in {"fail", "failed", "error"}:
            return "failed"
    elif isinstance(raw_status, int) and not isinstance(raw_status, bool):
        if raw_status == 1:
            return "success"
        if raw_status == 0:
            return "failed"
    return "unknown"


class WalletTransaction(BaseModel):
    signature: str
    timestamp: datetime | None = None
    time: datetime | None = None
    block_time: OptionalCount = None
    type: str = "unknown"
    tx_type: str = "unknown"
    slot: OptionalCount = None
    fee_lamports: OptionalCount = None
    status: Literal["success", "failed", "unknown"] = "unknown"
    signer: list[str] = Field(default_factory=list)
    program_ids: list[str] = Field(default_factory=list)


class WalletHistoryLimit(BaseModel):
    max_transactions: int
    requested_limit: int
    returned_count: int = 0
    max_pages: int = 1
    pages_fetched: int = 0
    is_truncated: bool = False
    history_complete: bool | None = None
    limit_description: str


class WalletTransactionsData(BaseModel):
    source: Literal["solscan"] = "solscan"
    source_url: str
    updated_at: datetime
    status: WalletDataStatus
    reason: str | None = None
    http_status: int | None = None
    read_only: Literal[True] = True
    address: str
    transactions: list[WalletTransaction] = Field(default_factory=list)
    transaction_count: int = 0
    history_limit: WalletHistoryLimit
    limit_description: str


class SolscanWalletClient:
    BASE_URL = "https://pro-api.solscan.io/v2.0"
    DEFAULT_TX_LIMIT = 20
    MAX_TX_LIMIT = 40
    MAX_PAGES = 1
    ALLOWED_API_LIMITS = (10, 20, 30, 40)
    CACHE_TTL_SECONDS = 60

    def __init__(
        self,
        client: httpx.Client,
        api_key: str | None = None,
        *,
        limit: int = DEFAULT_TX_LIMIT,
        max_pages: int = MAX_PAGES,
        cache: SourceCache | None = None,
    ) -> None:
        self.client = client
        self.api_key = (
            api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        )
        # Strictly bound the number of recent transactions and cap pagination to 1 request.
        self.limit = max(1, min(int(limit), self.MAX_TX_LIMIT))
        self.max_pages = max(1, min(int(max_pages), self.MAX_PAGES))
        self.api_limit = next(
            (val for val in self.ALLOWED_API_LIMITS if val >= self.limit),
            self.MAX_TX_LIMIT,
        )
        self.cache = cache if self.limit == self.DEFAULT_TX_LIMIT else None

    def fetch_wallet_transactions(self, address: str) -> WalletTransactionsData:
        cache_key = ("solana", address, "solscan_wallet_transactions")
        if self.api_key and self.cache is not None:
            cached = self.cache.get(cache_key, WalletTransactionsData)
            if cached is not None:
                return cached

        now = datetime.now(timezone.utc)
        endpoint_url = f"{self.BASE_URL}/account/transactions"
        source_url = f"{endpoint_url}?address={address}&limit={self.api_limit}"

        if not self.api_key:
            desc = (
                f"Solscan Pro API key is not configured; wallet transaction history was not requested "
                f"(bounded to max_transactions={self.limit}, max_pages={self.max_pages})."
            )
            limit_info = WalletHistoryLimit(
                max_transactions=self.limit,
                requested_limit=self.api_limit,
                returned_count=0,
                max_pages=self.max_pages,
                pages_fetched=0,
                is_truncated=False,
                history_complete=None,
                limit_description=desc,
            )
            return WalletTransactionsData(
                source_url=source_url,
                updated_at=now,
                status="not_configured",
                reason="missing_api_key",
                address=address,
                transactions=[],
                transaction_count=0,
                history_limit=limit_info,
                limit_description=desc,
            )

        status, reason, http_status, raw_data = self._request_transactions(
            endpoint_url, {"address": address, "limit": self.api_limit}
        )

        if status in ("unauthorized", "rate_limited", "unavailable"):
            desc = (
                f"Solscan Pro API wallet transaction request failed ({reason or status}); "
                f"history is unavailable (bounded to max_transactions={self.limit}, max_pages={self.max_pages})."
            )
            limit_info = WalletHistoryLimit(
                max_transactions=self.limit,
                requested_limit=self.api_limit,
                returned_count=0,
                max_pages=self.max_pages,
                pages_fetched=0,
                is_truncated=False,
                history_complete=None,
                limit_description=desc,
            )
            return WalletTransactionsData(
                source_url=source_url,
                updated_at=now,
                status=status,
                reason=reason,
                http_status=http_status,
                address=address,
                transactions=[],
                transaction_count=0,
                history_limit=limit_info,
                limit_description=desc,
            )

        if status == "no_data":
            desc = (
                f"No recent transactions returned by Solscan Pro API for this wallet "
                f"(checked latest up to max_transactions={self.limit}, max_pages={self.max_pages})."
            )
            limit_info = WalletHistoryLimit(
                max_transactions=self.limit,
                requested_limit=self.api_limit,
                returned_count=0,
                max_pages=self.max_pages,
                pages_fetched=1,
                is_truncated=False,
                history_complete=True,
                limit_description=desc,
            )
            return WalletTransactionsData(
                source_url=source_url,
                updated_at=now,
                status="no_data",
                reason="not_found",
                http_status=http_status,
                address=address,
                transactions=[],
                transaction_count=0,
                history_limit=limit_info,
                limit_description=desc,
            )

        raw_items: list[Any] | None = None
        if isinstance(raw_data, list):
            raw_items = raw_data
        elif isinstance(raw_data, dict) and isinstance(raw_data.get("items"), list):
            raw_items = raw_data["items"]
        elif isinstance(raw_data, dict) and isinstance(raw_data.get("transactions"), list):
            raw_items = raw_data["transactions"]

        if raw_items is None:
            desc = (
                f"Solscan Pro API returned an invalid transactions payload "
                f"(bounded to max_transactions={self.limit}, max_pages={self.max_pages})."
            )
            limit_info = WalletHistoryLimit(
                max_transactions=self.limit,
                requested_limit=self.api_limit,
                returned_count=0,
                max_pages=self.max_pages,
                pages_fetched=0,
                is_truncated=False,
                history_complete=None,
                limit_description=desc,
            )
            return WalletTransactionsData(
                source_url=source_url,
                updated_at=now,
                status="unavailable",
                reason="invalid_payload",
                http_status=http_status,
                address=address,
                transactions=[],
                transaction_count=0,
                history_limit=limit_info,
                limit_description=desc,
            )

        parsed_txs, had_malformed = self._parse_transactions(raw_items)
        if raw_items and not parsed_txs and had_malformed:
            desc = (
                f"Solscan Pro API returned malformed transaction entries without valid signatures "
                f"(bounded to max_transactions={self.limit}, max_pages={self.max_pages})."
            )
            limit_info = WalletHistoryLimit(
                max_transactions=self.limit,
                requested_limit=self.api_limit,
                returned_count=0,
                max_pages=self.max_pages,
                pages_fetched=1,
                is_truncated=False,
                history_complete=None,
                limit_description=desc,
            )
            return WalletTransactionsData(
                source_url=source_url,
                updated_at=now,
                status="unavailable",
                reason="invalid_payload",
                http_status=http_status,
                address=address,
                transactions=[],
                transaction_count=0,
                history_limit=limit_info,
                limit_description=desc,
            )

        bounded_txs = parsed_txs[: self.limit]
        returned_count = len(bounded_txs)

        if returned_count == 0:
            desc = (
                f"No recent transactions returned by Solscan Pro API for this wallet "
                f"(checked latest up to max_transactions={self.limit}, max_pages={self.max_pages})."
            )
            limit_info = WalletHistoryLimit(
                max_transactions=self.limit,
                requested_limit=self.api_limit,
                returned_count=0,
                max_pages=self.max_pages,
                pages_fetched=1,
                is_truncated=False,
                history_complete=True,
                limit_description=desc,
            )
            return WalletTransactionsData(
                source_url=source_url,
                updated_at=now,
                status="no_data",
                reason="not_found",
                http_status=http_status,
                address=address,
                transactions=[],
                transaction_count=0,
                history_limit=limit_info,
                limit_description=desc,
            )

        is_truncated = len(raw_items) >= self.limit or len(parsed_txs) > self.limit
        history_complete = not is_truncated
        if is_truncated:
            desc = (
                f"Returned {returned_count} most recent transaction(s) from Solscan Pro API "
                f"(history bounded to max_transactions={self.limit}, max_pages={self.max_pages}; "
                f"older wallet transactions were not fetched)."
            )
        else:
            desc = (
                f"Returned {returned_count} recent transaction(s) from Solscan Pro API "
                f"within bounded window (max_transactions={self.limit}, max_pages={self.max_pages}; "
                f"fewer than limit returned)."
            )

        limit_info = WalletHistoryLimit(
            max_transactions=self.limit,
            requested_limit=self.api_limit,
            returned_count=returned_count,
            max_pages=self.max_pages,
            pages_fetched=1,
            is_truncated=is_truncated,
            history_complete=history_complete,
            limit_description=desc,
        )

        result = WalletTransactionsData(
            source_url=source_url,
            updated_at=now,
            status="ok",
            reason=None,
            http_status=http_status,
            address=address,
            transactions=bounded_txs,
            transaction_count=returned_count,
            history_limit=limit_info,
            limit_description=desc,
        )

        if self.cache is not None and result.status == "ok" and bounded_txs:
            self.cache.store(cache_key, result, ttl=self.CACHE_TTL_SECONDS)

        return result

    def _request_transactions(
        self, url: str, params: dict[str, Any]
    ) -> tuple[WalletDataStatus, str | None, int | None, Any]:
        if not self.api_key:
            return "not_configured", "missing_api_key", None, None

        try:
            response = self.client.get(
                url,
                params=params,
                headers={
                    "token": self.api_key,
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException:
            return "unavailable", "timeout", None, None
        except httpx.HTTPError:
            return "unavailable", "http_error", None, None

        code = response.status_code
        if code in (401, 403):
            return "unauthorized", "access_denied", code, None
        if code == 429:
            return "rate_limited", "rate_limited", code, None
        if code == 404:
            return "no_data", "not_found", code, None
        if code != 200:
            return "unavailable", "http_error", code, None

        try:
            payload = response.json()
        except ValueError:
            return "unavailable", "invalid_payload", code, None

        if not isinstance(payload, dict):
            return "unavailable", "invalid_payload", code, None

        if payload.get("success") is False:
            errors = payload.get("errors")
            err_code = errors.get("code") if isinstance(errors, dict) else None
            if err_code in (401, 403):
                return "unauthorized", "access_denied", int(err_code), None
            if err_code == 429:
                return "rate_limited", "rate_limited", 429, None
            return "unavailable", "http_error", code, None

        if "data" not in payload:
            return "unavailable", "invalid_payload", code, None

        data = payload.get("data")
        if data is None or data == [] or data == {}:
            return "no_data", "not_found", code, None

        return "ok", None, code, data

    def _parse_transactions(
        self, raw_items: list[Any]
    ) -> tuple[list[WalletTransaction], bool]:
        parsed: list[WalletTransaction] = []
        had_malformed = False

        for item in raw_items:
            if not isinstance(item, dict):
                had_malformed = True
                continue

            raw_sig = item.get("tx_hash") or item.get("signature") or item.get("txHash")
            if not isinstance(raw_sig, str) or not raw_sig.strip():
                had_malformed = True
                continue
            signature = raw_sig.strip()

            block_time = _parse_optional_int(
                item.get("block_time") if "block_time" in item else item.get("blockTime")
            )
            timestamp = _parse_timestamp(block_time, item.get("time"))
            tx_type = _extract_tx_type(item)
            slot = _parse_optional_int(item.get("slot"))
            fee = _parse_optional_int(item.get("fee"))
            tx_status = _parse_tx_status(item.get("status"))

            raw_signer = item.get("signer")
            signers: list[str] = []
            if isinstance(raw_signer, list):
                signers = [
                    s.strip()
                    for s in raw_signer
                    if isinstance(s, str) and s.strip()
                ]
            elif isinstance(raw_signer, str) and raw_signer.strip():
                signers = [raw_signer.strip()]

            raw_programs = item.get("program_ids")
            program_ids: list[str] = []
            if isinstance(raw_programs, list):
                program_ids = [
                    p.strip()
                    for p in raw_programs
                    if isinstance(p, str) and p.strip()
                ]

            parsed.append(
                WalletTransaction(
                    signature=signature,
                    timestamp=timestamp,
                    time=timestamp,
                    block_time=block_time if block_time is not None and block_time > 0 else None,
                    type=tx_type,
                    tx_type=tx_type,
                    slot=slot,
                    fee_lamports=fee,
                    status=tx_status,
                    signer=signers,
                    program_ids=program_ids,
                )
            )

        return parsed, had_malformed


def get_wallet_client(request: Request) -> Iterator[SolscanWalletClient]:
    settings: Settings = getattr(request.app.state, "settings", Settings.from_env())
    if (
        get_dexscreener_client in request.app.dependency_overrides
        and get_wallet_client not in request.app.dependency_overrides
    ):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(503, json={"detail": "offline_test_transport"})
        )
        with httpx.Client(transport=transport, timeout=10.0) as offline_client:
            yield SolscanWalletClient(offline_client, None)
        return

    with httpx.Client(timeout=10.0) as client:
        yield SolscanWalletClient(
            client,
            settings.solscan_api_key,
            cache=getattr(request.app.state, "source_cache", None),
        )
