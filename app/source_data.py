"""Common, additive source contract used by token security reports."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PROVIDER_TIMEOUT = 10.0


class SourceError(BaseModel):
    source: str
    status: str
    reason: str
    http_status: int | None = None
    message: str | None = None


class CombinedSourcesResult(BaseModel):
    status: Literal["ok", "partial", "no_data", "unavailable"]
    partial: bool
    market_data: Any
    gmgn_activity: Any
    security_data: Any
    onchain_data: Any
    sources_status: dict[str, str] = Field(default_factory=dict)
    source_errors: list[SourceError] = Field(default_factory=list)


class SourceValue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    value: Any = None
    unit: str
    sourceId: str | None = None
    url: str | None = None
    timestamp: datetime | None = None


class NormalizedSourceData(BaseModel):
    price: dict[str, SourceValue] = Field(default_factory=dict)
    liquidity: dict[str, SourceValue] = Field(default_factory=dict)
    holders: dict[str, SourceValue] = Field(default_factory=dict)
    flags: dict[str, SourceValue] = Field(default_factory=dict)


class SourceRecorder:
    """Record provenance when an adapter supplies or replaces a selected value.

    Equal values retain the first observation that established them. Missing
    collections are null; actual numeric zero and boolean false are preserved.
    """

    def __init__(self) -> None:
        self.data = NormalizedSourceData()

    def capture(self, source: Any, *, activity: BaseModel, liquidity: BaseModel,
                holders: BaseModel, flags: list[BaseModel]) -> None:
        groups = {
            "price": {"price_usd": activity.price_usd,
                      "price_native_sol": activity.price_native_sol},
            "liquidity": liquidity.model_dump(),
            "holders": holders.model_dump(),
        }
        for group, values in groups.items():
            target = getattr(self.data, group)
            for key, value in values.items():
                if value == []:
                    value = None
                unit = self._unit(key)
                if key not in target:
                    target[key] = SourceValue(unit=unit)
                if value is not None and target[key].value != value:
                    target[key] = SourceValue(value=value, unit=unit,
                                             sourceId=source.source,
                                             url=source.source_url,
                                             timestamp=source.updated_at)
        for flag in flags:
            if flag.source == source.source:
                self.data.flags[f"{flag.source}:{flag.code}"] = SourceValue(
                    value=flag.value, unit="signal", sourceId=source.source,
                    url=source.source_url, timestamp=source.updated_at,
                )

    @staticmethod
    def _unit(key: str) -> str:
        if key.endswith("_usd"):
            return "USD"
        if key.endswith("_sol"):
            return "SOL"
        if key.endswith("_pct"):
            return "percent"
        if key.endswith("_count"):
            return "count"
        if key.endswith("_address"):
            return "address"
        if key == "creator_balance":
            return "token"
        return "records"


def _build_unavailable_onchain(address: str, now: datetime, reason: str) -> Any:
    from app.onchain_data import (
        HolderSampleSummary,
        OnChainTokenMetadata,
        OnChainTokenSupply,
        SolscanClient,
        TokenOnChainData,
    )

    meta_url = f"{SolscanClient.BASE_URL}/token/meta?address={address}"
    holders_url = (
        f"{SolscanClient.BASE_URL}/token/holders?address={address}&page=1"
        f"&page_size={SolscanClient.DEFAULT_PAGE_SIZE}"
    )
    desc = f"Solscan Pro API request failed ({reason}); holder sample is unavailable."
    sample = HolderSampleSummary(
        page=1,
        page_size=SolscanClient.DEFAULT_PAGE_SIZE,
        max_pages=SolscanClient.MAX_PAGES,
        pages_fetched=0,
        sample_size=0,
        top_10_count=0,
        calculation_basis="unavailable",
        sample_description=desc,
    )
    return TokenOnChainData(
        meta_source_url=meta_url,
        holders_source_url=holders_url,
        updated_at=now,
        status="unavailable",
        reason=reason,
        address=address,
        metadata=OnChainTokenMetadata(address=address),
        supply=OnChainTokenSupply(),
        holders=[],
        holder_sample=sample,
        sample_description=desc,
    )


def _build_unavailable_security(address: str, now: datetime, reason: str) -> Any:
    from app.security_data import (
        ContractAuthorities,
        ExtendedMarketActivity,
        HolderDistribution,
        LiquiditySecurity,
        SecurityDataClient,
        SecurityRiskSummary,
        SecuritySourceStatus,
        TokenSecurityData,
        TokenVerificationMetadata,
    )

    urls = {
        "rugcheck": f"{SecurityDataClient.RUGCHECK_BASE_URL}/{address}/report",
        "dexscreener": f"{SecurityDataClient.DEXSCREENER_BASE_URL}/{address}",
        "dextools": f"{SecurityDataClient.DEXTOOLS_BASE_URL}/{address}/audit",
        "gmgn": f"{SecurityDataClient.GMGN_BASE_URL}/{address}",
    }
    sources = {
        name: SecuritySourceStatus(
            source=name,
            status="unavailable",
            reason=reason,
            source_url=url,
            updated_at=now,
        )
        for name, url in urls.items()
    }
    return TokenSecurityData(
        normalized_data=NormalizedSourceData(),
        address=address,
        overall_status="unavailable",
        updated_at=now,
        risk_summary=SecurityRiskSummary(),
        authorities=ContractAuthorities(),
        holder_distribution=HolderDistribution(),
        liquidity_security=LiquiditySecurity(),
        market_activity=ExtendedMarketActivity(),
        verification_and_metadata=TokenVerificationMetadata(),
        normalized_flags={},
        flags=[],
        sources=sources,
        ai_context_payload={"address": address, "overall_status": "unavailable"},
    )


def _default_reason_for_status(status: str, existing_reason: str | None) -> str:
    if existing_reason:
        return existing_reason
    if status == "not_configured":
        return "missing_api_key"
    if status == "unauthorized":
        return "access_denied"
    if status == "rate_limited":
        return "rate_limited"
    return "source_error"


def combine_token_sources(
    address: str,
    *,
    market_provider: Any,
    gmgn_provider: Any,
    security_provider: Any,
    solscan_provider: Any,
    provider_timeout: float = DEFAULT_PROVIDER_TIMEOUT,
    allow_partial: bool = False,
) -> CombinedSourcesResult:
    """Fetch all token data sources in parallel with a per-provider timeout.

    Failures or timeouts in optional/auxiliary providers (GMGN, Solscan, RugCheck,
    DexTools) never block market data and are returned as a partial report with
    a per-source list of errors.
    """
    from app.market_data import (
        DexScreenerClient,
        MarketDataError,
        MarketDataTimeout,
        TokenMarketData,
    )
    from app.onchain_data import TokenOnChainData
    from app.security_data import SecurityDataClient, TokenSecurityData
    from app.trading_activity import GmgnActivity

    now = datetime.now(timezone.utc)
    timeout = max(0.001, float(provider_timeout))

    executor = ThreadPoolExecutor(max_workers=4)
    try:
        deadline = monotonic() + timeout
        market_future = executor.submit(market_provider.fetch_token_market, address)
        gmgn_future = executor.submit(gmgn_provider.fetch_activity, address)
        solscan_future = executor.submit(solscan_provider.fetch_token_onchain, address)
        security_future = executor.submit(security_provider.fetch_token_security, address)

        # 1. Market data (DexScreener)
        try:
            market_raw = market_future.result(timeout=max(0.0, deadline - monotonic()))
            market_data = TokenMarketData.model_validate(market_raw)
        except (FuturesTimeoutError, MarketDataTimeout, httpx.TimeoutException) as error:
            if not allow_partial:
                raise MarketDataTimeout("Market data request timed out") from error
            market_data = TokenMarketData(
                source_url=f"{DexScreenerClient.BASE_URL}/{address}",
                status="unavailable",
                reason="timeout",
                updated_at=None,
                pairs=[],
            )
        except Exception as error:
            if not allow_partial:
                if isinstance(error, MarketDataError):
                    raise
                raise MarketDataError("Market data provider failed") from error
            market_data = TokenMarketData(
                source_url=f"{DexScreenerClient.BASE_URL}/{address}",
                status="unavailable",
                reason="source_error",
                updated_at=None,
                pairs=[],
            )

        # 2. GMGN trading activity (never blocks market data)
        try:
            gmgn_raw = gmgn_future.result(timeout=max(0.0, deadline - monotonic()))
            gmgn_activity = GmgnActivity.model_validate(gmgn_raw)
        except (FuturesTimeoutError, httpx.TimeoutException):
            gmgn_activity = GmgnActivity(
                updated_at=now, status="unavailable", reason="timeout"
            )
        except Exception:
            gmgn_activity = GmgnActivity(
                updated_at=now, status="unavailable", reason="source_error"
            )

        # 3. Solscan on-chain metadata, supply & holder sample (never blocks market data)
        try:
            solscan_raw = solscan_future.result(timeout=max(0.0, deadline - monotonic()))
            onchain_data = TokenOnChainData.model_validate(solscan_raw)
        except (FuturesTimeoutError, httpx.TimeoutException):
            onchain_data = _build_unavailable_onchain(address, now, reason="timeout")
        except Exception:
            onchain_data = _build_unavailable_onchain(address, now, reason="source_error")

        # 4. Security data (RugCheck, DexScreener, DexTools, GMGN security)
        try:
            security_raw = security_future.result(timeout=max(0.0, deadline - monotonic()))
            security_data = TokenSecurityData.model_validate(security_raw)
        except (FuturesTimeoutError, httpx.TimeoutException):
            security_data = _build_unavailable_security(address, now, reason="timeout")
        except Exception:
            security_data = _build_unavailable_security(address, now, reason="source_error")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if isinstance(security_provider, SecurityDataClient):
        security_data = security_provider.apply_market_data_fallback(
            security_data, market_data
        )

    source_errors: list[SourceError] = []
    sources_status: dict[str, str] = {}

    # DexScreener status & errors
    sources_status["dexscreener"] = market_data.status
    if market_data.status == "unavailable":
        ds_reason = _default_reason_for_status(market_data.status, market_data.reason)
        source_errors.append(
            SourceError(
                source="dexscreener",
                status=market_data.status,
                reason=ds_reason,
                message=f"DEX Screener market data unavailable ({ds_reason}).",
            )
        )

    # GMGN status & errors
    sources_status["gmgn"] = gmgn_activity.status
    if gmgn_activity.status not in ("ok", "no_data"):
        gmgn_reason = _default_reason_for_status(
            gmgn_activity.status, getattr(gmgn_activity, "reason", None)
        )
        source_errors.append(
            SourceError(
                source="gmgn",
                status=gmgn_activity.status,
                reason=gmgn_reason,
                message=f"GMGN activity source returned {gmgn_activity.status} ({gmgn_reason}).",
            )
        )

    # Solscan status & errors
    sources_status["solscan"] = onchain_data.status
    if onchain_data.status not in ("ok", "no_data"):
        solscan_reason = _default_reason_for_status(
            onchain_data.status, onchain_data.reason
        )
        source_errors.append(
            SourceError(
                source="solscan",
                status=onchain_data.status,
                reason=solscan_reason,
                http_status=onchain_data.http_status,
                message=f"Solscan on-chain source returned {onchain_data.status} ({solscan_reason}).",
            )
        )

    # Security sub-sources (RugCheck, DexTools)
    for sec_source in ("rugcheck", "dextools"):
        sec_item = security_data.sources.get(sec_source) if security_data.sources else None
        sec_status = sec_item.status if sec_item is not None else "unavailable"
        sources_status[sec_source] = sec_status
        if sec_status not in ("ok", "no_data"):
            sec_reason = _default_reason_for_status(
                sec_status, sec_item.reason if sec_item is not None else None
            )
            source_errors.append(
                SourceError(
                    source=sec_source,
                    status=sec_status,
                    reason=sec_reason,
                    http_status=sec_item.http_status if sec_item is not None else None,
                    message=f"{sec_source} security source returned {sec_status} ({sec_reason}).",
                )
            )

    statuses = list(sources_status.values())
    has_ok = any(s in ("ok", "partial") for s in statuses)
    has_no_data = any(s == "no_data" for s in statuses)
    has_errors = len(source_errors) > 0 or any(s == "partial" for s in statuses)

    if has_ok and not has_errors:
        overall_status: Literal["ok", "partial", "no_data", "unavailable"] = "ok"
        is_partial = False
    elif has_ok and has_errors:
        overall_status = "partial"
        is_partial = True
    elif has_no_data:
        overall_status = "no_data"
        is_partial = has_errors
    else:
        overall_status = "unavailable"
        is_partial = False

    return CombinedSourcesResult(
        status=overall_status,
        partial=is_partial,
        market_data=market_data,
        gmgn_activity=gmgn_activity,
        security_data=security_data,
        onchain_data=onchain_data,
        sources_status=sources_status,
        source_errors=source_errors,
    )
