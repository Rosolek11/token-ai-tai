"""On-chain token metadata, supply, and bounded holder sample via Solscan Pro API v2.0."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Literal

import httpx
from fastapi import Request
from pydantic import BaseModel, Field

from app.config import Settings
from app.market_data import (
    OptionalAmount,
    OptionalCount,
    get_dexscreener_client,
    normalize_optional_number,
)

OnChainStatus = Literal[
    "ok",
    "partial",
    "no_data",
    "not_configured",
    "unauthorized",
    "rate_limited",
    "unavailable",
]


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        dec = Decimal(value)
        return dec if dec >= 0 else None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")) or value < 0:
            return None
        return Decimal(str(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            dec = Decimal(stripped)
            return dec if dec.is_finite() and dec >= 0 else None
        except InvalidOperation:
            return None
    return None


def _parse_optional_amount(value: object) -> float | None:
    try:
        normalized = normalize_optional_number(value)
        if normalized is None:
            return None
        result = float(normalized)
        if result != result or result in (float("inf"), float("-inf")) or result < 0:
            return None
        return result
    except (ValueError, TypeError):
        return None


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


class OnChainTokenMetadata(BaseModel):
    address: str
    name: str | None = None
    symbol: str | None = None
    icon: str | None = None
    decimals: OptionalCount = None
    holder_count: OptionalCount = None
    creator: str | None = None
    create_tx: str | None = None
    created_time: OptionalCount = None
    created_at: datetime | None = None
    mint_authority: str | None = None
    freeze_authority: str | None = None
    first_mint_tx: str | None = None
    first_mint_time: OptionalCount = None
    market_cap_usd: OptionalAmount = None
    price_usd: OptionalAmount = None
    volume_24h_usd: OptionalAmount = None


class OnChainTokenSupply(BaseModel):
    raw_amount: str | None = None
    decimals: OptionalCount = None
    ui_amount: OptionalAmount = None
    circulating_supply: OptionalAmount = None


class OnChainHolder(BaseModel):
    rank: int
    address: str
    owner: str | None = None
    raw_amount: str | None = None
    decimals: OptionalCount = None
    ui_amount: OptionalAmount = None
    value_usd: OptionalAmount = None
    share_percent: OptionalAmount = None


class HolderSampleSummary(BaseModel):
    page: int = 1
    page_size: int = 10
    max_pages: int = 1
    pages_fetched: int = 0
    sample_size: int = 0
    top_10_count: int = 0
    total_holders: OptionalCount = None
    top_1_share_percent: OptionalAmount = None
    top_5_share_percent: OptionalAmount = None
    top_10_share_percent: OptionalAmount = None
    calculation_basis: Literal["total_supply", "provider_percentage", "unavailable"] = (
        "unavailable"
    )
    sample_description: str


class TokenOnChainData(BaseModel):
    source: Literal["solscan"] = "solscan"
    meta_source_url: str
    holders_source_url: str
    updated_at: datetime
    status: OnChainStatus
    reason: str | None = None
    http_status: int | None = None
    read_only: Literal[True] = True
    address: str
    metadata: OnChainTokenMetadata
    supply: OnChainTokenSupply
    holders: list[OnChainHolder] = Field(default_factory=list)
    holder_sample: HolderSampleSummary
    total_supply: OptionalAmount = None
    decimals: OptionalCount = None
    holder_count: OptionalCount = None
    top_10_share_percent: OptionalAmount = None
    sample_description: str


class SolscanClient:
    BASE_URL = "https://pro-api.solscan.io/v2.0"
    DEFAULT_PAGE_SIZE = 10
    MAX_PAGE_SIZE = 20
    MAX_PAGES = 1

    def __init__(
        self,
        client: httpx.Client,
        api_key: str | None = None,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.client = client
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        # Strictly bound pagination to a single page and at most MAX_PAGE_SIZE items.
        self.page_size = max(1, min(int(page_size), self.MAX_PAGE_SIZE))
        self.max_pages = max(1, min(int(max_pages), self.MAX_PAGES))

    def _request_endpoint(
        self, url: str, params: dict[str, Any]
    ) -> tuple[OnChainStatus, str | None, int | None, Any]:
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
        if data is None or data == {} or data == []:
            return "no_data", "not_found", code, None

        return "ok", None, code, data

    def fetch_token_onchain(self, address: str) -> TokenOnChainData:
        now = datetime.now(timezone.utc)
        meta_url = f"{self.BASE_URL}/token/meta"
        holders_url = f"{self.BASE_URL}/token/holders"
        meta_source_url = f"{meta_url}?address={address}"
        holders_source_url = (
            f"{holders_url}?address={address}&page=1&page_size={self.page_size}"
        )

        metadata = OnChainTokenMetadata(address=address)
        supply = OnChainTokenSupply()

        if not self.api_key:
            desc = (
                "Solscan Pro API key is not configured; on-chain metadata and holder sample were not requested."
            )
            sample = HolderSampleSummary(
                page=1,
                page_size=self.page_size,
                max_pages=self.max_pages,
                pages_fetched=0,
                sample_size=0,
                top_10_count=0,
                calculation_basis="unavailable",
                sample_description=desc,
            )
            return TokenOnChainData(
                meta_source_url=meta_source_url,
                holders_source_url=holders_source_url,
                updated_at=now,
                status="not_configured",
                reason="missing_api_key",
                address=address,
                metadata=metadata,
                supply=supply,
                holders=[],
                holder_sample=sample,
                sample_description=desc,
            )

        # Step 1: Fetch token metadata & supply and confirm API access before requesting holders.
        meta_status, meta_reason, meta_http, meta_data = self._request_endpoint(
            meta_url, {"address": address}
        )
        if meta_status in ("unauthorized", "rate_limited", "unavailable"):
            desc = (
                f"Solscan Pro API access failed ({meta_reason or meta_status}); holder pagination was skipped."
            )
            sample = HolderSampleSummary(
                page=1,
                page_size=self.page_size,
                max_pages=self.max_pages,
                pages_fetched=0,
                sample_size=0,
                top_10_count=0,
                calculation_basis="unavailable",
                sample_description=desc,
            )
            return TokenOnChainData(
                meta_source_url=meta_source_url,
                holders_source_url=holders_source_url,
                updated_at=now,
                status=meta_status,
                reason=meta_reason,
                http_status=meta_http,
                address=address,
                metadata=metadata,
                supply=supply,
                holders=[],
                holder_sample=sample,
                sample_description=desc,
            )

        raw_supply_dec: Decimal | None = None
        ui_supply_dec: Decimal | None = None

        if meta_status == "ok":
            if not isinstance(meta_data, dict):
                desc = "Solscan Pro API returned an invalid metadata payload."
                sample = HolderSampleSummary(
                    page=1,
                    page_size=self.page_size,
                    max_pages=self.max_pages,
                    pages_fetched=0,
                    sample_description=desc,
                )
                return TokenOnChainData(
                    meta_source_url=meta_source_url,
                    holders_source_url=holders_source_url,
                    updated_at=now,
                    status="unavailable",
                    reason="invalid_payload",
                    http_status=meta_http,
                    address=address,
                    metadata=metadata,
                    supply=supply,
                    holders=[],
                    holder_sample=sample,
                    sample_description=desc,
                )

            raw_supply_dec, ui_supply_dec = self._populate_meta_and_supply(
                meta_data, metadata=metadata, supply=supply
            )

        # Step 2: Fetch bounded holder sample (strictly capped at page=1, max_pages=1).
        pages_fetched = 0
        raw_holder_items: list[Any] = []
        reported_total_holders: int | None = metadata.holder_count

        holders_status, holders_reason, holders_http, holders_data = (
            self._request_endpoint(
                holders_url,
                {"address": address, "page": 1, "page_size": self.page_size},
            )
        )
        if holders_status == "ok":
            pages_fetched = 1
            if isinstance(holders_data, dict):
                total_val = _parse_optional_int(holders_data.get("total"))
                if total_val is not None:
                    reported_total_holders = total_val
                    if metadata.holder_count is None:
                        metadata.holder_count = total_val
                items = holders_data.get("items")
                if items is None:
                    raw_holder_items = []
                elif isinstance(items, list):
                    raw_holder_items = items
                else:
                    holders_status = "unavailable"
                    holders_reason = "invalid_payload"
            elif isinstance(holders_data, list):
                raw_holder_items = holders_data
            else:
                holders_status = "unavailable"
                holders_reason = "invalid_payload"
        elif holders_status == "no_data":
            pages_fetched = 1

        parsed_holders, basis, top_1, top_5, top_10 = self._parse_holders_and_shares(
            raw_holder_items,
            token_decimals=supply.decimals,
            raw_supply_dec=raw_supply_dec,
            ui_supply_dec=ui_supply_dec,
        )

        # Determine overall status and reason
        if meta_status == "ok" and holders_status == "ok":
            final_status: OnChainStatus = "ok"
            final_reason: str | None = None
            final_http = holders_http or meta_http
        elif meta_status == "no_data" and holders_status == "no_data":
            final_status = "no_data"
            final_reason = "not_found"
            final_http = holders_http or meta_http
        elif meta_status == "ok" and holders_status == "no_data":
            final_status = "ok"
            final_reason = None
            final_http = meta_http
        elif meta_status == "no_data" and holders_status == "ok":
            final_status = "ok" if parsed_holders else "no_data"
            final_reason = None if parsed_holders else "not_found"
            final_http = holders_http
        elif meta_status == "ok" or holders_status == "ok":
            final_status = "partial"
            final_reason = holders_reason or meta_reason
            final_http = holders_http or meta_http
        else:
            final_status = holders_status
            final_reason = holders_reason or meta_reason
            final_http = holders_http or meta_http

        top_10_count = min(10, len(parsed_holders))
        sample_size = len(parsed_holders)
        total_str = (
            str(reported_total_holders)
            if reported_total_holders is not None
            else "unknown"
        )
        if top_10 is not None:
            basis_label = (
                "token total supply"
                if basis == "total_supply"
                else "Solscan holder percentages"
            )
            sample_desc = (
                f"Top {top_10_count} holders from Solscan Pro API sample "
                f"(page=1, page_size={self.page_size}, max_pages={self.max_pages}, "
                f"sample_size={sample_size}, total_holders={total_str}) "
                f"control {top_10:.4f}% of {basis_label}."
            )
        elif sample_size == 0:
            sample_desc = (
                f"No holders returned in Solscan Pro API sample "
                f"(page=1, page_size={self.page_size}, max_pages={self.max_pages}, "
                f"total_holders={total_str}); top 10 share is unavailable."
            )
        else:
            sample_desc = (
                f"Fetched {sample_size} holder(s) from Solscan Pro API sample "
                f"(page=1, page_size={self.page_size}, max_pages={self.max_pages}), "
                f"but total token supply is missing or zero so top 10 share could not be computed."
            )

        holder_sample = HolderSampleSummary(
            page=1,
            page_size=self.page_size,
            max_pages=self.max_pages,
            pages_fetched=pages_fetched,
            sample_size=sample_size,
            top_10_count=top_10_count,
            total_holders=reported_total_holders,
            top_1_share_percent=top_1,
            top_5_share_percent=top_5,
            top_10_share_percent=top_10,
            calculation_basis=basis,
            sample_description=sample_desc,
        )

        return TokenOnChainData(
            meta_source_url=meta_source_url,
            holders_source_url=holders_source_url,
            updated_at=now,
            status=final_status,
            reason=final_reason,
            http_status=final_http,
            address=address,
            metadata=metadata,
            supply=supply,
            holders=parsed_holders,
            holder_sample=holder_sample,
            total_supply=supply.ui_amount,
            decimals=supply.decimals,
            holder_count=metadata.holder_count,
            top_10_share_percent=top_10,
            sample_description=sample_desc,
        )

    def _populate_meta_and_supply(
        self,
        data: dict[str, Any],
        *,
        metadata: OnChainTokenMetadata,
        supply: OnChainTokenSupply,
    ) -> tuple[Decimal | None, Decimal | None]:
        for key in ("name", "symbol", "icon", "creator", "create_tx", "first_mint_tx"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                setattr(metadata, key, val.strip())

        if data.get("mint_authority") is not None:
            ma = str(data["mint_authority"]).strip()
            metadata.mint_authority = ma or None
        if data.get("freeze_authority") is not None:
            fa = str(data["freeze_authority"]).strip()
            metadata.freeze_authority = fa or None

        decimals = _parse_optional_int(data.get("decimals"))
        metadata.decimals = decimals
        supply.decimals = decimals

        holders_cnt = _parse_optional_int(
            data.get("holder") if "holder" in data else data.get("holders")
        )
        metadata.holder_count = holders_cnt

        created_time = _parse_optional_int(data.get("created_time"))
        metadata.created_time = created_time
        if created_time is not None and created_time > 0:
            metadata.created_at = datetime.fromtimestamp(created_time, tz=timezone.utc)

        metadata.first_mint_time = _parse_optional_int(data.get("first_mint_time"))
        metadata.price_usd = _parse_optional_amount(data.get("price"))
        metadata.volume_24h_usd = _parse_optional_amount(data.get("volume_24h"))
        metadata.market_cap_usd = _parse_optional_amount(data.get("market_cap"))

        raw_supply_val = data.get("supply")
        raw_supply_dec = _parse_decimal(raw_supply_val)
        ui_supply_dec: Decimal | None = None

        if raw_supply_dec is not None:
            supply.raw_amount = str(raw_supply_val).strip()
            if decimals is not None and decimals >= 0:
                ui_supply_dec = raw_supply_dec / (Decimal(10) ** decimals)
            else:
                ui_supply_dec = raw_supply_dec
            supply.ui_amount = float(round(ui_supply_dec, 8))

        circ_val = _parse_optional_amount(data.get("circulating_supply"))
        if circ_val is not None:
            supply.circulating_supply = circ_val

        return raw_supply_dec, ui_supply_dec

    def _parse_holders_and_shares(
        self,
        raw_items: list[Any],
        *,
        token_decimals: int | None,
        raw_supply_dec: Decimal | None,
        ui_supply_dec: Decimal | None,
    ) -> tuple[
        list[OnChainHolder],
        Literal["total_supply", "provider_percentage", "unavailable"],
        float | None,
        float | None,
        float | None,
    ]:
        parsed: list[OnChainHolder] = []
        used_supply_basis = False
        used_provider_pct_basis = False

        for idx, item in enumerate(raw_items[: self.page_size], start=1):
            if not isinstance(item, dict):
                continue
            addr = str(item.get("address") or item.get("owner") or "").strip()
            if not addr:
                continue
            owner = (
                str(item["owner"]).strip()
                if isinstance(item.get("owner"), str) and item["owner"].strip()
                else None
            )
            rank = _parse_optional_int(item.get("rank")) or idx
            item_decimals = _parse_optional_int(item.get("decimals"))
            effective_decimals = (
                item_decimals if item_decimals is not None else token_decimals
            )

            raw_amt_val = item.get("amount")
            raw_amt_dec = _parse_decimal(raw_amt_val)
            ui_amt_val = _parse_optional_amount(item.get("ui_amount"))
            ui_amt_dec = _parse_decimal(item.get("ui_amount"))

            if ui_amt_dec is None and raw_amt_dec is not None:
                if effective_decimals is not None and effective_decimals >= 0:
                    ui_amt_dec = raw_amt_dec / (Decimal(10) ** effective_decimals)
                else:
                    ui_amt_dec = raw_amt_dec
                ui_amt_val = float(round(ui_amt_dec, 8))

            share_pct: float | None = None
            if (
                raw_amt_dec is not None
                and raw_supply_dec is not None
                and raw_supply_dec > 0
                and effective_decimals == token_decimals
            ):
                pct_dec = (raw_amt_dec / raw_supply_dec) * Decimal(100)
                share_pct = float(round(min(Decimal(100), pct_dec), 4))
                used_supply_basis = True
            elif (
                ui_amt_dec is not None
                and ui_supply_dec is not None
                and ui_supply_dec > 0
            ):
                pct_dec = (ui_amt_dec / ui_supply_dec) * Decimal(100)
                share_pct = float(round(min(Decimal(100), pct_dec), 4))
                used_supply_basis = True
            else:
                prov_pct = _parse_optional_amount(
                    item.get("percentage")
                    if "percentage" in item
                    else item.get("pct")
                )
                if prov_pct is not None and prov_pct <= 100.0:
                    share_pct = round(prov_pct, 4)
                    used_provider_pct_basis = True

            parsed.append(
                OnChainHolder(
                    rank=rank,
                    address=addr,
                    owner=owner,
                    raw_amount=str(raw_amt_val).strip()
                    if raw_amt_val is not None and not isinstance(raw_amt_val, bool)
                    else None,
                    decimals=effective_decimals,
                    ui_amount=ui_amt_val,
                    value_usd=_parse_optional_amount(item.get("value")),
                    share_percent=share_pct,
                )
            )

        top_10_slice = parsed[:10]
        shares = [h.share_percent for h in top_10_slice if h.share_percent is not None]
        if not top_10_slice or len(shares) != len(top_10_slice):
            return parsed, "unavailable", None, None, None

        basis: Literal["total_supply", "provider_percentage", "unavailable"] = (
            "total_supply" if used_supply_basis else "provider_percentage" if used_provider_pct_basis else "unavailable"
        )
        top_1 = round(min(100.0, shares[0]), 4)
        top_5 = round(min(100.0, sum(shares[:5])), 4)
        top_10 = round(min(100.0, sum(shares[:10])), 4)
        return parsed, basis, top_1, top_5, top_10


def get_solscan_client(request: Request) -> Iterator[SolscanClient]:
    settings: Settings = getattr(request.app.state, "settings", Settings.from_env())
    if (
        get_dexscreener_client in request.app.dependency_overrides
        and get_solscan_client not in request.app.dependency_overrides
    ):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(503, json={"detail": "offline_test_transport"})
        )
        with httpx.Client(transport=transport, timeout=10.0) as offline_client:
            yield SolscanClient(offline_client, None)
        return

    with httpx.Client(timeout=10.0) as client:
        yield SolscanClient(client, settings.solscan_api_key)
