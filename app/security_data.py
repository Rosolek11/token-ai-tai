from datetime import datetime, timezone
from typing import Annotated, Any, Iterator, Literal

import httpx
from fastapi import Request
from pydantic import BaseModel, BeforeValidator, Field

from app.config import Settings
from app.market_data import (
    OptionalAmount,
    OptionalNumber,
    TokenMarketData,
    get_dexscreener_client,
    normalize_optional_number,
)

SecuritySourceName = Literal["rugcheck", "dexscreener", "dextools", "gmgn"]
SourceStatusValue = Literal["ok", "no_data", "unavailable"]
FlagSeverity = Literal["info", "ok", "low", "warn", "high", "critical"]
FlagStatus = Literal["safe", "warning", "danger", "unknown", "info"]
FlagCategory = Literal[
    "authority",
    "liquidity",
    "holders",
    "contract",
    "market",
    "verification",
    "insiders",
]
RiskLevel = Literal["low", "medium", "high", "critical", "unknown"]


def _parse_yes_no_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true", "1", "active", "enabled"}:
            return True
        if normalized in {"no", "false", "0", "renounced", "disabled"}:
            return False
    return None


def _safe_float(value: object) -> float | None:
    try:
        normalized = normalize_optional_number(value)
        if normalized is None:
            return None
        result = float(normalized)
        if result != result or result in (float("inf"), float("-inf")):
            return None
        return result
    except (ValueError, TypeError):
        return None


def _safe_non_negative_float(value: object) -> float | None:
    result = _safe_float(value)
    if result is None or result < 0:
        return None
    return result


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


OptionalNonNegativeInt = Annotated[
    int | None,
    BeforeValidator(_safe_int),
]


class SecuritySourceStatus(BaseModel):
    source: SecuritySourceName
    status: SourceStatusValue
    reason: str | None = None
    http_status: int | None = None
    source_url: str
    updated_at: datetime
    read_only: Literal[True] = True


class NormalizedSecurityFlag(BaseModel):
    code: str
    title: str
    category: FlagCategory
    severity: FlagSeverity
    status: FlagStatus
    value: str | float | int | bool | None = None
    description: str
    source: Literal["rugcheck", "dexscreener", "dextools", "gmgn", "aggregated"]


class TokenHolderInfo(BaseModel):
    address: str
    owner: str | None = None
    pct: OptionalAmount = None
    ui_amount: OptionalAmount = None
    is_insider: bool | None = None
    is_locked: bool | None = None


class LiquidityPoolSecurity(BaseModel):
    dex: str | None = None
    pair_address: str
    liquidity_usd: OptionalAmount = None
    lp_locked_pct: OptionalAmount = None
    lp_locked_usd: OptionalAmount = None
    lp_unlocked_usd: OptionalAmount = None


class SecurityRiskSummary(BaseModel):
    risk_score: OptionalAmount = None
    normalized_score: OptionalAmount = None
    safety_score: OptionalAmount = None
    risk_level: RiskLevel = "unknown"
    rugged: bool | None = None
    is_honeypot: bool | None = None
    verdict_summary: str = "Security data has not been evaluated yet."
    total_flags_count: int = 0
    critical_flags_count: int = 0
    warning_flags_count: int = 0
    safe_flags_count: int = 0


class ContractAuthorities(BaseModel):
    mint_authority: str | None = None
    mint_authority_active: bool | None = None
    freeze_authority: str | None = None
    freeze_authority_active: bool | None = None
    update_authority: str | None = None
    mutable_metadata: bool | None = None
    token_program: str | None = None
    is_token_2022: bool | None = None
    transfer_fee_pct: OptionalAmount = None
    transfer_fee_authority: str | None = None
    permanent_delegate: str | None = None
    non_transferable: bool | None = None
    is_open_source: bool | None = None
    is_proxy: bool | None = None
    is_contract_renounced: bool | None = None


class HolderDistribution(BaseModel):
    holder_count: OptionalNonNegativeInt = None
    top_holder_pct: OptionalAmount = None
    top_holder_address: str | None = None
    top_5_holders_pct: OptionalAmount = None
    top_10_holders_pct: OptionalAmount = None
    top_20_holders_pct: OptionalAmount = None
    creator_address: str | None = None
    creator_balance: OptionalAmount = None
    creator_balance_pct: OptionalAmount = None
    owner_address: str | None = None
    owner_balance_pct: OptionalAmount = None
    insider_networks_count: OptionalNonNegativeInt = None
    insider_holders_count: OptionalNonNegativeInt = None
    insider_supply_pct: OptionalAmount = None
    bundled_supply_pct: OptionalAmount = None
    sniper_holders_count: OptionalNonNegativeInt = None
    sniper_supply_pct: OptionalAmount = None
    dev_rug_history_count: OptionalNonNegativeInt = None
    top_holders: list[TokenHolderInfo] = Field(default_factory=list)


class LiquiditySecurity(BaseModel):
    total_market_liquidity_usd: OptionalAmount = None
    lp_locked_pct: OptionalAmount = None
    lp_burned_pct: OptionalAmount = None
    lp_locked_usd: OptionalAmount = None
    lp_unlocked_usd: OptionalAmount = None
    lp_providers_count: OptionalNonNegativeInt = None
    markets_count: OptionalNonNegativeInt = None
    lockers_count: OptionalNonNegativeInt = None
    pools: list[LiquidityPoolSecurity] = Field(default_factory=list)


class ExtendedMarketActivity(BaseModel):
    token_name: str | None = None
    token_symbol: str | None = None
    token_decimals: OptionalNonNegativeInt = None
    total_supply: OptionalAmount = None
    circulating_supply: OptionalAmount = None
    fdv_usd: OptionalAmount = None
    market_cap_usd: OptionalAmount = None
    price_native_sol: OptionalAmount = None
    price_usd: OptionalAmount = None
    liquidity_usd: OptionalAmount = None
    liquidity_base: OptionalAmount = None
    liquidity_quote: OptionalAmount = None
    volume_5m_usd: OptionalAmount = None
    volume_1h_usd: OptionalAmount = None
    volume_6h_usd: OptionalAmount = None
    volume_24h_usd: OptionalAmount = None
    price_change_5m_percent: OptionalNumber = None
    price_change_1h_percent: OptionalNumber = None
    price_change_6h_percent: OptionalNumber = None
    price_change_24h_percent: OptionalNumber = None
    buys_5m: OptionalNonNegativeInt = None
    sells_5m: OptionalNonNegativeInt = None
    buys_1h: OptionalNonNegativeInt = None
    sells_1h: OptionalNonNegativeInt = None
    buys_6h: OptionalNonNegativeInt = None
    sells_6h: OptionalNonNegativeInt = None
    buys_24h: OptionalNonNegativeInt = None
    sells_24h: OptionalNonNegativeInt = None
    total_txns_24h: OptionalNonNegativeInt = None
    buy_sell_ratio_24h: OptionalAmount = None
    pair_created_at: datetime | None = None
    pair_age_hours: OptionalAmount = None
    active_boosts: OptionalNonNegativeInt = None
    pair_labels: list[str] = Field(default_factory=list)
    total_pairs_count: int = 0
    dex_list: list[str] = Field(default_factory=list)


class TokenVerificationMetadata(BaseModel):
    jupiter_verified: bool | None = None
    jupiter_strict: bool | None = None
    rugcheck_verified: bool | None = None
    dextools_score: OptionalAmount = None
    description: str | None = None
    image_url: str | None = None
    websites: list[str] = Field(default_factory=list)
    socials: list[dict[str, str]] = Field(default_factory=list)
    buy_tax_pct: OptionalAmount = None
    sell_tax_pct: OptionalAmount = None
    slippage_modifiable: bool | None = None
    is_blacklisted: bool | None = None
    is_potentially_scam: bool | None = None


class TokenSecurityData(BaseModel):
    address: str
    overall_status: Literal["ok", "partial", "no_data", "unavailable"]
    read_only: Literal[True] = True
    updated_at: datetime
    risk_summary: SecurityRiskSummary
    authorities: ContractAuthorities
    holder_distribution: HolderDistribution
    liquidity_security: LiquiditySecurity
    market_activity: ExtendedMarketActivity
    verification_and_metadata: TokenVerificationMetadata
    normalized_flags: dict[str, bool | None]
    flags: list[NormalizedSecurityFlag]
    sources: dict[SecuritySourceName, SecuritySourceStatus]
    ai_context_payload: dict[str, Any]


class SecurityDataClient:
    RUGCHECK_BASE_URL = "https://api.rugcheck.xyz/v1/tokens"
    DEXSCREENER_BASE_URL = "https://api.dexscreener.com/token-pairs/v1/solana"
    DEXTOOLS_BASE_URL = "https://public-api.dextools.io/trial/v2/token/solana"
    GMGN_BASE_URL = "https://gmgn.ai/defi/quotation/v1/tokens/security/sol"

    def __init__(
        self,
        client: httpx.Client,
        *,
        rugcheck_api_key: str | None = None,
        dextools_api_key: str | None = None,
        gmgn_api_key: str | None = None,
    ) -> None:
        self.client = client
        self.rugcheck_api_key = rugcheck_api_key
        self.dextools_api_key = dextools_api_key
        self.gmgn_api_key = gmgn_api_key

    def _get_json_read_only(
        self,
        source: SecuritySourceName,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> tuple[SecuritySourceStatus, Any]:
        now = datetime.now(timezone.utc)
        request_headers = {"Accept": "application/json", **(headers or {})}
        try:
            response = self.client.get(url, headers=request_headers)
        except httpx.TimeoutException:
            return (
                SecuritySourceStatus(
                    source=source,
                    status="unavailable",
                    reason="timeout",
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )
        except httpx.HTTPError:
            return (
                SecuritySourceStatus(
                    source=source,
                    status="unavailable",
                    reason="http_error",
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )

        status_code = response.status_code
        if status_code == 429:
            return (
                SecuritySourceStatus(
                    source=source,
                    status="unavailable",
                    reason="rate_limited",
                    http_status=429,
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )
        if status_code in (401, 403):
            reason = (
                "missing_api_key"
                if (source == "dextools" and not self.dextools_api_key)
                or (source == "gmgn" and not self.gmgn_api_key)
                else "access_denied"
            )
            return (
                SecuritySourceStatus(
                    source=source,
                    status="unavailable",
                    reason=reason,
                    http_status=status_code,
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )
        if status_code == 404:
            return (
                SecuritySourceStatus(
                    source=source,
                    status="no_data",
                    reason="not_found",
                    http_status=404,
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )
        if status_code != 200:
            return (
                SecuritySourceStatus(
                    source=source,
                    status="unavailable",
                    reason="http_error",
                    http_status=status_code,
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )

        try:
            payload = response.json()
        except ValueError:
            return (
                SecuritySourceStatus(
                    source=source,
                    status="unavailable",
                    reason="invalid_payload",
                    http_status=status_code,
                    source_url=url,
                    updated_at=now,
                ),
                None,
            )

        return (
            SecuritySourceStatus(
                source=source,
                status="ok",
                http_status=200,
                source_url=url,
                updated_at=now,
            ),
            payload,
        )

    def fetch_token_security(
        self,
        address: str,
        *,
        market_data: TokenMarketData | None = None,
    ) -> TokenSecurityData:
        now = datetime.now(timezone.utc)
        authorities = ContractAuthorities()
        holders = HolderDistribution()
        liquidity = LiquiditySecurity()
        activity = ExtendedMarketActivity()
        verification = TokenVerificationMetadata()
        risk_summary = SecurityRiskSummary()
        flags: list[NormalizedSecurityFlag] = []
        sources: dict[SecuritySourceName, SecuritySourceStatus] = {}

        # 1. RugCheck report (read-only GET)
        rugcheck_url = f"{self.RUGCHECK_BASE_URL}/{address}/report"
        rugcheck_headers: dict[str, str] = {}
        if self.rugcheck_api_key:
            rugcheck_headers["X-API-KEY"] = self.rugcheck_api_key
            rugcheck_headers["Authorization"] = f"Bearer {self.rugcheck_api_key}"
        rc_status, rc_payload = self._get_json_read_only(
            "rugcheck", rugcheck_url, rugcheck_headers
        )
        if rc_status.status == "ok":
            if not isinstance(rc_payload, dict) or not rc_payload:
                rc_status = rc_status.model_copy(
                    update={
                        "status": "no_data" if rc_payload == {} else "unavailable",
                        "reason": "not_found" if rc_payload == {} else "invalid_payload",
                    }
                )
            elif rc_payload.get("error"):
                err_msg = str(rc_payload.get("error")).lower()
                is_not_found = "not found" in err_msg or "no data" in err_msg
                rc_status = rc_status.model_copy(
                    update={
                        "status": "no_data" if is_not_found else "unavailable",
                        "reason": "not_found" if is_not_found else "http_error",
                    }
                )
            else:
                self._apply_rugcheck_data(
                    rc_payload,
                    authorities=authorities,
                    holders=holders,
                    liquidity=liquidity,
                    activity=activity,
                    verification=verification,
                    risk_summary=risk_summary,
                    flags=flags,
                )
        sources["rugcheck"] = rc_status

        # 2. DexScreener pair & security telemetry (read-only GET)
        dexscreener_url = f"{self.DEXSCREENER_BASE_URL}/{address}"
        ds_status, ds_payload = self._get_json_read_only("dexscreener", dexscreener_url)
        if ds_status.status == "ok":
            if ds_payload is None or ds_payload == []:
                ds_status = ds_status.model_copy(
                    update={"status": "no_data", "reason": "not_found"}
                )
                if market_data is not None and market_data.status == "ok":
                    ds_status = ds_status.model_copy(
                        update={"status": "ok", "reason": None}
                    )
                    self._apply_market_data_fallback(
                        market_data, activity=activity, liquidity=liquidity, flags=flags
                    )
            elif isinstance(ds_payload, list):
                matched = self._apply_dexscreener_data(
                    address,
                    ds_payload,
                    now=now,
                    activity=activity,
                    liquidity=liquidity,
                    verification=verification,
                    flags=flags,
                )
                if not matched:
                    ds_status = ds_status.model_copy(
                        update={"status": "no_data", "reason": "not_found"}
                    )
            else:
                ds_status = ds_status.model_copy(
                    update={"status": "unavailable", "reason": "invalid_payload"}
                )
        elif market_data is not None:
            self._apply_market_data_fallback(
                market_data, activity=activity, liquidity=liquidity, flags=flags
            )
            if market_data.status == "ok":
                ds_status = SecuritySourceStatus(
                    source="dexscreener",
                    status="ok",
                    http_status=200,
                    source_url=market_data.source_url,
                    updated_at=market_data.updated_at,
                )
            elif market_data.status == "no_data":
                ds_status = SecuritySourceStatus(
                    source="dexscreener",
                    status="no_data",
                    reason="not_found",
                    http_status=200,
                    source_url=market_data.source_url,
                    updated_at=market_data.updated_at,
                )
        sources["dexscreener"] = ds_status

        # 3. DexTools audit report (read-only GET, official API only, no scraping)
        dextools_url = f"{self.DEXTOOLS_BASE_URL}/{address}/audit"
        dextools_headers: dict[str, str] = {}
        if self.dextools_api_key:
            dextools_headers["X-API-Key"] = self.dextools_api_key
        dt_status, dt_payload = self._get_json_read_only(
            "dextools", dextools_url, dextools_headers
        )
        if dt_status.status == "ok":
            if not isinstance(dt_payload, dict):
                dt_status = dt_status.model_copy(
                    update={"status": "unavailable", "reason": "invalid_payload"}
                )
            else:
                dt_data = (
                    dt_payload.get("data")
                    if "data" in dt_payload
                    else dt_payload
                )
                if dt_data is None or dt_data == {}:
                    dt_status = dt_status.model_copy(
                        update={"status": "no_data", "reason": "not_found"}
                    )
                elif not isinstance(dt_data, dict):
                    dt_status = dt_status.model_copy(
                        update={"status": "unavailable", "reason": "invalid_payload"}
                    )
                else:
                    self._apply_dextools_data(
                        dt_data,
                        authorities=authorities,
                        holders=holders,
                        verification=verification,
                        risk_summary=risk_summary,
                        flags=flags,
                    )
        sources["dextools"] = dt_status

        # 4. GMGN Agent API read-only security info (only if account has access, no scraping, no trading)
        gmgn_url = f"{self.GMGN_BASE_URL}/{address}"
        if not self.gmgn_api_key:
            sources["gmgn"] = SecuritySourceStatus(
                source="gmgn",
                status="unavailable",
                reason="missing_api_key",
                source_url=gmgn_url,
                updated_at=now,
            )
        else:
            gmgn_headers = {
                "Authorization": f"Bearer {self.gmgn_api_key}",
                "X-API-KEY": self.gmgn_api_key,
            }
            gmgn_status, gmgn_payload = self._get_json_read_only(
                "gmgn", gmgn_url, gmgn_headers
            )
            if gmgn_status.status == "ok":
                if not isinstance(gmgn_payload, dict):
                    gmgn_status = gmgn_status.model_copy(
                        update={"status": "unavailable", "reason": "invalid_payload"}
                    )
                elif gmgn_payload.get("code") not in (None, 0, 200):
                    code_val = gmgn_payload.get("code")
                    msg_val = str(gmgn_payload.get("msg") or gmgn_payload.get("message") or "").lower()
                    reason = (
                        "rate_limited"
                        if code_val == 429 or "rate" in msg_val or "limit" in msg_val
                        else "access_denied"
                    )
                    gmgn_status = gmgn_status.model_copy(
                        update={"status": "unavailable", "reason": reason}
                    )
                else:
                    gmgn_data = (
                        gmgn_payload.get("data")
                        if "data" in gmgn_payload
                        else gmgn_payload
                    )
                    if isinstance(gmgn_data, dict) and isinstance(
                        gmgn_data.get("security"), dict
                    ):
                        gmgn_data = gmgn_data["security"]
                    if gmgn_data is None or gmgn_data == {}:
                        gmgn_status = gmgn_status.model_copy(
                            update={"status": "no_data", "reason": "not_found"}
                        )
                    elif not isinstance(gmgn_data, dict):
                        gmgn_status = gmgn_status.model_copy(
                            update={"status": "unavailable", "reason": "invalid_payload"}
                        )
                    else:
                        self._apply_gmgn_data(
                            gmgn_data,
                            authorities=authorities,
                            holders=holders,
                            liquidity=liquidity,
                            verification=verification,
                            risk_summary=risk_summary,
                            flags=flags,
                        )
            sources["gmgn"] = gmgn_status

        normalized_flags = self._build_normalized_flags(
            authorities=authorities,
            holders=holders,
            liquidity=liquidity,
            activity=activity,
            verification=verification,
            risk_summary=risk_summary,
            flags=flags,
        )
        self._finalize_risk_summary(
            risk_summary=risk_summary,
            authorities=authorities,
            holders=holders,
            liquidity=liquidity,
            verification=verification,
            flags=flags,
            sources=sources,
        )

        statuses = [s.status for s in sources.values()]
        if all(s == "ok" for s in statuses):
            overall_status: Literal["ok", "partial", "no_data", "unavailable"] = "ok"
        elif any(s == "ok" for s in statuses):
            overall_status = "partial"
        elif any(s == "no_data" for s in statuses):
            overall_status = "no_data"
        else:
            overall_status = "unavailable"

        ai_context_payload = {
            "address": address,
            "overall_status": overall_status,
            "read_only": True,
            "updated_at": now.isoformat(),
            "sources_availability": {
                name: {
                    "status": src.status,
                    "reason": src.reason,
                    "http_status": src.http_status,
                }
                for name, src in sources.items()
            },
            "risk_summary": risk_summary.model_dump(mode="json"),
            "authorities": authorities.model_dump(mode="json"),
            "holder_distribution": holders.model_dump(mode="json"),
            "liquidity_security": liquidity.model_dump(mode="json"),
            "market_activity": activity.model_dump(mode="json"),
            "verification_and_metadata": verification.model_dump(mode="json"),
            "normalized_flags": normalized_flags,
            "flags": [flag.model_dump(mode="json") for flag in flags],
        }

        return TokenSecurityData(
            address=address,
            overall_status=overall_status,
            updated_at=now,
            risk_summary=risk_summary,
            authorities=authorities,
            holder_distribution=holders,
            liquidity_security=liquidity,
            market_activity=activity,
            verification_and_metadata=verification,
            normalized_flags=normalized_flags,
            flags=flags,
            sources=sources,
            ai_context_payload=ai_context_payload,
        )

    def _apply_rugcheck_data(
        self,
        payload: dict[str, Any],
        *,
        authorities: ContractAuthorities,
        holders: HolderDistribution,
        liquidity: LiquiditySecurity,
        activity: ExtendedMarketActivity,
        verification: TokenVerificationMetadata,
        risk_summary: SecurityRiskSummary,
        flags: list[NormalizedSecurityFlag],
    ) -> None:
        token_obj = payload.get("token") if isinstance(payload.get("token"), dict) else {}
        token_meta = (
            payload.get("tokenMeta") if isinstance(payload.get("tokenMeta"), dict) else {}
        )
        file_meta = (
            payload.get("fileMeta") if isinstance(payload.get("fileMeta"), dict) else {}
        )

        # Token & contract authorities
        if "mintAuthority" in payload or "mintAuthority" in token_obj:
            mint_auth = payload.get("mintAuthority") or token_obj.get("mintAuthority")
            authorities.mint_authority = str(mint_auth) if mint_auth else None
            authorities.mint_authority_active = bool(mint_auth)
            flags.append(
                NormalizedSecurityFlag(
                    code="mint_authority",
                    title="Mint authority",
                    category="authority",
                    severity="critical" if mint_auth else "ok",
                    status="danger" if mint_auth else "safe",
                    value=str(mint_auth) if mint_auth else "Renounced",
                    description=(
                        "Mint authority is active; new tokens can be minted."
                        if mint_auth
                        else "Mint authority is renounced (disabled)."
                    ),
                    source="rugcheck",
                )
            )

        if "freezeAuthority" in payload or "freezeAuthority" in token_obj:
            freeze_auth = payload.get("freezeAuthority") or token_obj.get("freezeAuthority")
            authorities.freeze_authority = str(freeze_auth) if freeze_auth else None
            authorities.freeze_authority_active = bool(freeze_auth)
            flags.append(
                NormalizedSecurityFlag(
                    code="freeze_authority",
                    title="Freeze authority",
                    category="authority",
                    severity="high" if freeze_auth else "ok",
                    status="danger" if freeze_auth else "safe",
                    value=str(freeze_auth) if freeze_auth else "Renounced",
                    description=(
                        "Freeze authority is active; token accounts can be frozen."
                        if freeze_auth
                        else "Freeze authority is renounced (disabled)."
                    ),
                    source="rugcheck",
                )
            )

        if "mutable" in token_meta:
            mutable = _parse_yes_no_bool(token_meta.get("mutable"))
            if mutable is not None:
                authorities.mutable_metadata = mutable
                flags.append(
                    NormalizedSecurityFlag(
                        code="mutable_metadata",
                        title="Metadata mutability",
                        category="authority",
                        severity="warn" if mutable else "ok",
                        status="warning" if mutable else "safe",
                        value=mutable,
                        description=(
                            "Token metadata is mutable and can be modified by update authority."
                            if mutable
                            else "Token metadata is immutable."
                        ),
                        source="rugcheck",
                    )
                )

        if token_meta.get("updateAuthority"):
            authorities.update_authority = str(token_meta["updateAuthority"])

        if payload.get("tokenProgram"):
            prog = str(payload["tokenProgram"])
            authorities.token_program = prog
            authorities.is_token_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb" in prog or "2022" in prog.lower()

        transfer_fee = payload.get("transferFee")
        if isinstance(transfer_fee, dict):
            pct = _safe_non_negative_float(transfer_fee.get("pct"))
            if pct is not None:
                authorities.transfer_fee_pct = pct
                if pct > 0:
                    flags.append(
                        NormalizedSecurityFlag(
                            code="transfer_fee",
                            title="Transfer fee",
                            category="contract",
                            severity="high" if pct >= 5 else "warn",
                            status="danger" if pct >= 5 else "warning",
                            value=pct,
                            description=f"Token charges a {pct:.2f}% transfer fee.",
                            source="rugcheck",
                        )
                    )
            if transfer_fee.get("authority"):
                authorities.transfer_fee_authority = str(transfer_fee["authority"])

        # Token supply, decimals, name, symbol
        decimals = _safe_int(token_obj.get("decimals"))
        if decimals is not None:
            activity.token_decimals = decimals
        raw_supply = _safe_non_negative_float(token_obj.get("supply"))
        if raw_supply is not None:
            if decimals is not None and decimals > 0 and raw_supply > 10**decimals:
                activity.total_supply = raw_supply / (10**decimals)
            else:
                activity.total_supply = raw_supply

        name = token_meta.get("name") or file_meta.get("name")
        symbol = token_meta.get("symbol") or file_meta.get("symbol")
        if isinstance(name, str) and name.strip():
            activity.token_name = name.strip()
        if isinstance(symbol, str) and symbol.strip():
            activity.token_symbol = symbol.strip()
        if isinstance(file_meta.get("image"), str) and file_meta["image"].strip():
            verification.image_url = file_meta["image"].strip()
        if isinstance(file_meta.get("description"), str) and file_meta["description"].strip():
            verification.description = file_meta["description"].strip()

        # Holders & concentration
        total_holders = _safe_int(payload.get("totalHolders"))
        if total_holders is not None:
            holders.holder_count = total_holders

        if payload.get("creator"):
            holders.creator_address = str(payload["creator"])
        creator_bal = _safe_non_negative_float(payload.get("creatorBalance"))
        if creator_bal is not None:
            holders.creator_balance = creator_bal
            if activity.total_supply and activity.total_supply > 0:
                pct_val = (creator_bal / activity.total_supply) * 100.0
                if pct_val <= 100.0:
                    holders.creator_balance_pct = round(pct_val, 4)

        raw_holders = payload.get("topHolders")
        if isinstance(raw_holders, list) and raw_holders:
            parsed_holders: list[TokenHolderInfo] = []
            for item in raw_holders[:20]:
                if not isinstance(item, dict) or not item.get("address"):
                    continue
                pct = _safe_non_negative_float(item.get("pct"))
                ui_amt = _safe_non_negative_float(
                    item.get("uiAmount") if item.get("uiAmount") is not None else item.get("amount")
                )
                insider = _parse_yes_no_bool(item.get("insider"))
                parsed_holders.append(
                    TokenHolderInfo(
                        address=str(item["address"]),
                        owner=str(item["owner"]) if item.get("owner") else None,
                        pct=round(pct, 4) if pct is not None else None,
                        ui_amount=ui_amt,
                        is_insider=insider,
                    )
                )
            holders.top_holders = parsed_holders
            pcts = [h.pct for h in parsed_holders if h.pct is not None]
            if pcts:
                holders.top_holder_pct = round(pcts[0], 4)
                holders.top_holder_address = parsed_holders[0].address
                holders.top_5_holders_pct = round(sum(pcts[:5]), 4)
                holders.top_10_holders_pct = round(sum(pcts[:10]), 4)
                holders.top_20_holders_pct = round(sum(pcts[:20]), 4)
                if holders.top_10_holders_pct >= 50:
                    flags.append(
                        NormalizedSecurityFlag(
                            code="top_holders_concentration",
                            title="High top-10 holder concentration",
                            category="holders",
                            severity="high" if holders.top_10_holders_pct >= 70 else "warn",
                            status="danger" if holders.top_10_holders_pct >= 70 else "warning",
                            value=holders.top_10_holders_pct,
                            description=f"Top 10 holders control {holders.top_10_holders_pct:.2f}% of token supply.",
                            source="rugcheck",
                        )
                    )
                else:
                    flags.append(
                        NormalizedSecurityFlag(
                            code="top_holders_concentration",
                            title="Top-10 holder concentration",
                            category="holders",
                            severity="ok",
                            status="safe",
                            value=holders.top_10_holders_pct,
                            description=f"Top 10 holders control {holders.top_10_holders_pct:.2f}% of token supply.",
                            source="rugcheck",
                        )
                    )
            insider_holders = [h for h in parsed_holders if h.is_insider]
            if insider_holders:
                holders.insider_holders_count = len(insider_holders)
                holders.insider_supply_pct = round(
                    sum(h.pct or 0.0 for h in insider_holders), 4
                )

        insider_nets = payload.get("insiderNetworks")
        if isinstance(insider_nets, list):
            holders.insider_networks_count = len(insider_nets)
        elif _safe_int(payload.get("graphInsidersDetected")) is not None:
            holders.insider_networks_count = _safe_int(payload.get("graphInsidersDetected"))

        # Liquidity & LP locks
        tot_liq = _safe_non_negative_float(payload.get("totalMarketLiquidity"))
        if tot_liq is not None:
            liquidity.total_market_liquidity_usd = round(tot_liq, 2)
        lp_prov = _safe_int(payload.get("totalLPProviders"))
        if lp_prov is not None:
            liquidity.lp_providers_count = lp_prov
        lockers = payload.get("lockers")
        if isinstance(lockers, dict):
            liquidity.lockers_count = len(lockers)

        markets = payload.get("markets")
        if isinstance(markets, list) and markets:
            liquidity.markets_count = len(markets)
            pools: list[LiquidityPoolSecurity] = []
            locked_pcts: list[float] = []
            total_locked_usd = 0.0
            total_unlocked_usd = 0.0
            has_usd = False
            for mkt in markets:
                if not isinstance(mkt, dict):
                    continue
                pubkey = str(mkt.get("pubkey") or "")
                if not pubkey:
                    continue
                lp = mkt.get("lp") if isinstance(mkt.get("lp"), dict) else {}
                locked_pct = _safe_non_negative_float(lp.get("lpLockedPct"))
                locked_usd = _safe_non_negative_float(lp.get("lpLockedUSD"))
                unlocked_usd = _safe_non_negative_float(lp.get("lpUnlocked"))
                if locked_pct is not None:
                    locked_pcts.append(locked_pct)
                if locked_usd is not None:
                    total_locked_usd += locked_usd
                    has_usd = True
                if unlocked_usd is not None:
                    total_unlocked_usd += unlocked_usd
                pools.append(
                    LiquidityPoolSecurity(
                        dex=str(mkt.get("marketType")) if mkt.get("marketType") else None,
                        pair_address=pubkey,
                        liquidity_usd=round(locked_usd + (unlocked_usd or 0.0), 2)
                        if locked_usd is not None
                        else None,
                        lp_locked_pct=round(locked_pct, 2) if locked_pct is not None else None,
                        lp_locked_usd=round(locked_usd, 2) if locked_usd is not None else None,
                        lp_unlocked_usd=round(unlocked_usd, 2) if unlocked_usd is not None else None,
                    )
                )
            liquidity.pools = pools
            if locked_pcts:
                liquidity.lp_locked_pct = round(max(locked_pcts), 2)
                flags.append(
                    NormalizedSecurityFlag(
                        code="lp_lock_status",
                        title="LP lock ratio",
                        category="liquidity",
                        severity="ok" if liquidity.lp_locked_pct >= 80 else "warn" if liquidity.lp_locked_pct >= 30 else "high",
                        status="safe" if liquidity.lp_locked_pct >= 80 else "warning" if liquidity.lp_locked_pct >= 30 else "danger",
                        value=liquidity.lp_locked_pct,
                        description=f"{liquidity.lp_locked_pct:.2f}% of LP tokens are locked or burned.",
                        source="rugcheck",
                    )
                )
            if has_usd:
                liquidity.lp_locked_usd = round(total_locked_usd, 2)
                liquidity.lp_unlocked_usd = round(total_unlocked_usd, 2)

        # Risks & scores
        if "rugged" in payload:
            rugged_val = _parse_yes_no_bool(payload.get("rugged"))
            if rugged_val is not None:
                risk_summary.rugged = rugged_val
                if rugged_val:
                    flags.append(
                        NormalizedSecurityFlag(
                            code="rugged",
                            title="Token marked as rugged",
                            category="market",
                            severity="critical",
                            status="danger",
                            value=True,
                            description="RugCheck marks this token as rugged.",
                            source="rugcheck",
                        )
                    )

        raw_score = _safe_non_negative_float(payload.get("score"))
        if raw_score is not None:
            risk_summary.risk_score = round(raw_score, 2)
        norm_score = _safe_non_negative_float(payload.get("score_normalised"))
        if norm_score is not None:
            bounded = min(100.0, norm_score)
            risk_summary.normalized_score = round(bounded, 2)
            risk_summary.safety_score = round(max(0.0, 100.0 - bounded), 2)

        verif = payload.get("verification")
        if isinstance(verif, dict):
            if "jup_verified" in verif:
                verification.jupiter_verified = _parse_yes_no_bool(verif.get("jup_verified"))
            if "jup_strict" in verif:
                verification.jupiter_strict = _parse_yes_no_bool(verif.get("jup_strict"))
            verification.rugcheck_verified = bool(
                verification.jupiter_verified or verification.jupiter_strict
            )
            if isinstance(verif.get("description"), str) and verif["description"].strip():
                verification.description = verif["description"].strip()

        raw_risks = payload.get("risks")
        if isinstance(raw_risks, list):
            for risk in raw_risks:
                if not isinstance(risk, dict):
                    continue
                name_str = str(risk.get("name") or "Security risk").strip()
                desc_str = str(risk.get("description") or name_str).strip()
                level_str = str(risk.get("level") or "warn").strip().lower()
                val_str = risk.get("value")
                severity: FlagSeverity = (
                    "critical"
                    if level_str in {"danger", "critical", "error"}
                    else "high"
                    if level_str == "high"
                    else "warn"
                    if level_str in {"warn", "warning", "medium"}
                    else "low"
                    if level_str == "low"
                    else "info"
                )
                status: FlagStatus = (
                    "danger"
                    if severity in {"critical", "high"}
                    else "warning"
                    if severity in {"warn", "low"}
                    else "info"
                )
                code_slug = (
                    name_str.lower()
                    .replace(" ", "_")
                    .replace("-", "_")
                    .replace("/", "_")
                )[:48] or "rugcheck_risk"
                flags.append(
                    NormalizedSecurityFlag(
                        code=f"rc_{code_slug}",
                        title=name_str,
                        category="contract",
                        severity=severity,
                        status=status,
                        value=str(val_str) if val_str not in (None, "") else None,
                        description=desc_str,
                        source="rugcheck",
                    )
                )

    def _apply_dexscreener_data(
        self,
        address: str,
        raw_pairs: list[Any],
        *,
        now: datetime,
        activity: ExtendedMarketActivity,
        liquidity: LiquiditySecurity,
        verification: TokenVerificationMetadata,
        flags: list[NormalizedSecurityFlag],
    ) -> bool:
        solana_pairs = [
            p
            for p in raw_pairs
            if isinstance(p, dict)
            and p.get("chainId") == "solana"
            and address
            in {
                (p.get("baseToken") or {}).get("address"),
                (p.get("quoteToken") or {}).get("address"),
            }
        ]
        if not solana_pairs:
            return False

        activity.total_pairs_count = len(solana_pairs)
        dexes: list[str] = []
        for pair in solana_pairs:
            dex_id = str(pair.get("dexId") or "").strip()
            if dex_id and dex_id not in dexes:
                dexes.append(dex_id)
        activity.dex_list = dexes

        base_pairs = [
            p
            for p in solana_pairs
            if (p.get("baseToken") or {}).get("address") == address
        ]
        primary = max(
            base_pairs or solana_pairs,
            key=lambda p: (
                _safe_non_negative_float((p.get("liquidity") or {}).get("usd")) is not None,
                _safe_non_negative_float((p.get("liquidity") or {}).get("usd")) or 0.0,
            ),
        )

        base_tok = primary.get("baseToken") if isinstance(primary.get("baseToken"), dict) else {}
        if not activity.token_name and base_tok.get("name"):
            activity.token_name = str(base_tok["name"])
        if not activity.token_symbol and base_tok.get("symbol"):
            activity.token_symbol = str(base_tok["symbol"])

        activity.price_usd = _safe_non_negative_float(primary.get("priceUsd"))
        activity.price_native_sol = _safe_non_negative_float(primary.get("priceNative"))
        activity.fdv_usd = _safe_non_negative_float(primary.get("fdv"))
        activity.market_cap_usd = _safe_non_negative_float(primary.get("marketCap"))

        liq = primary.get("liquidity") if isinstance(primary.get("liquidity"), dict) else {}
        activity.liquidity_usd = _safe_non_negative_float(liq.get("usd"))
        activity.liquidity_base = _safe_non_negative_float(liq.get("base"))
        activity.liquidity_quote = _safe_non_negative_float(liq.get("quote"))
        if activity.liquidity_usd is not None:
            total_liq = sum(
                _safe_non_negative_float((p.get("liquidity") or {}).get("usd")) or 0.0
                for p in solana_pairs
            )
            liquidity.total_market_liquidity_usd = max(
                liquidity.total_market_liquidity_usd or 0.0, round(total_liq, 2)
            )

        vol = primary.get("volume") if isinstance(primary.get("volume"), dict) else {}
        activity.volume_5m_usd = _safe_non_negative_float(vol.get("m5"))
        activity.volume_1h_usd = _safe_non_negative_float(vol.get("h1"))
        activity.volume_6h_usd = _safe_non_negative_float(vol.get("h6"))
        activity.volume_24h_usd = _safe_non_negative_float(vol.get("h24"))

        chg = primary.get("priceChange") if isinstance(primary.get("priceChange"), dict) else {}
        activity.price_change_5m_percent = _safe_float(chg.get("m5"))
        activity.price_change_1h_percent = _safe_float(chg.get("h1"))
        activity.price_change_6h_percent = _safe_float(chg.get("h6"))
        activity.price_change_24h_percent = _safe_float(chg.get("h24"))

        txns = primary.get("txns") if isinstance(primary.get("txns"), dict) else {}
        for window, buys_attr, sells_attr in (
            ("m5", "buys_5m", "sells_5m"),
            ("h1", "buys_1h", "sells_1h"),
            ("h6", "buys_6h", "sells_6h"),
            ("h24", "buys_24h", "sells_24h"),
        ):
            w_obj = txns.get(window)
            if isinstance(w_obj, dict):
                setattr(activity, buys_attr, _safe_int(w_obj.get("buys")))
                setattr(activity, sells_attr, _safe_int(w_obj.get("sells")))

        if activity.buys_24h is not None and activity.sells_24h is not None:
            activity.total_txns_24h = activity.buys_24h + activity.sells_24h
            if activity.sells_24h > 0:
                activity.buy_sell_ratio_24h = round(
                    activity.buys_24h / activity.sells_24h, 3
                )

        created_ms = _safe_int(primary.get("pairCreatedAt"))
        if created_ms is not None and created_ms > 0:
            created_dt = datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc)
            activity.pair_created_at = created_dt
            age_hours = max(0.0, (now - created_dt).total_seconds() / 3600.0)
            activity.pair_age_hours = round(age_hours, 2)

        boosts = primary.get("boosts") if isinstance(primary.get("boosts"), dict) else {}
        if boosts.get("active") is not None:
            activity.active_boosts = _safe_int(boosts.get("active"))

        labels = primary.get("labels")
        if isinstance(labels, list):
            activity.pair_labels = [str(lbl) for lbl in labels if isinstance(lbl, str)]

        info = primary.get("info") if isinstance(primary.get("info"), dict) else {}
        if not verification.image_url and isinstance(info.get("imageUrl"), str):
            verification.image_url = info["imageUrl"]
        websites = info.get("websites")
        if isinstance(websites, list):
            verification.websites = [
                str(w.get("url"))
                for w in websites
                if isinstance(w, dict) and isinstance(w.get("url"), str)
            ]
        socials = info.get("socials")
        if isinstance(socials, list):
            verification.socials = [
                {
                    "type": str(s.get("type") or "social"),
                    "url": str(s.get("url") or ""),
                }
                for s in socials
                if isinstance(s, dict) and s.get("url")
            ]

        if activity.liquidity_usd is not None:
            is_low_liq = activity.liquidity_usd < 10000.0
            flags.append(
                NormalizedSecurityFlag(
                    code="dex_liquidity_depth",
                    title="DEX pool liquidity depth",
                    category="liquidity",
                    severity="high" if activity.liquidity_usd < 1000.0 else "warn" if is_low_liq else "ok",
                    status="danger" if activity.liquidity_usd < 1000.0 else "warning" if is_low_liq else "safe",
                    value=activity.liquidity_usd,
                    description=(
                        f"Primary DEX pair has ${activity.liquidity_usd:,.2f} liquidity."
                    ),
                    source="dexscreener",
                )
            )

        return True

    def _apply_market_data_fallback(
        self,
        market_data: TokenMarketData,
        *,
        activity: ExtendedMarketActivity,
        liquidity: LiquiditySecurity,
        flags: list[NormalizedSecurityFlag],
    ) -> None:
        activity.total_pairs_count = len(market_data.pairs)
        activity.dex_list = list(
            dict.fromkeys(p.dex_id for p in market_data.pairs if p.dex_id)
        )
        activity.price_usd = market_data.price_usd
        activity.liquidity_usd = market_data.liquidity_usd
        activity.volume_24h_usd = market_data.volume_24h_usd
        activity.price_change_24h_percent = market_data.price_change_24h_percent
        if market_data.pairs:
            primary = next(
                (
                    p
                    for p in market_data.pairs
                    if p.pair_address == market_data.primary_pair_address
                ),
                market_data.pairs[0],
            )
            if not activity.token_name and primary.base_token.name:
                activity.token_name = primary.base_token.name
            if not activity.token_symbol and primary.base_token.symbol:
                activity.token_symbol = primary.base_token.symbol
        if market_data.liquidity_usd is not None:
            liquidity.total_market_liquidity_usd = max(
                liquidity.total_market_liquidity_usd or 0.0, market_data.liquidity_usd
            )
            flags.append(
                NormalizedSecurityFlag(
                    code="dex_liquidity_depth",
                    title="DEX pool liquidity depth",
                    category="liquidity",
                    severity="high"
                    if market_data.liquidity_usd < 1000.0
                    else "warn"
                    if market_data.liquidity_usd < 10000.0
                    else "ok",
                    status="danger"
                    if market_data.liquidity_usd < 1000.0
                    else "warning"
                    if market_data.liquidity_usd < 10000.0
                    else "safe",
                    value=market_data.liquidity_usd,
                    description=f"Primary DEX pair has ${market_data.liquidity_usd:,.2f} liquidity.",
                    source="dexscreener",
                )
            )

    def _apply_dextools_data(
        self,
        data: dict[str, Any],
        *,
        authorities: ContractAuthorities,
        holders: HolderDistribution,
        verification: TokenVerificationMetadata,
        risk_summary: SecurityRiskSummary,
        flags: list[NormalizedSecurityFlag],
    ) -> None:
        open_src = _parse_yes_no_bool(data.get("isOpenSource"))
        if open_src is not None:
            authorities.is_open_source = open_src
            flags.append(
                NormalizedSecurityFlag(
                    code="dextools_open_source",
                    title="Contract source verification",
                    category="contract",
                    severity="ok" if open_src else "warn",
                    status="safe" if open_src else "warning",
                    value=open_src,
                    description="Contract source is verified." if open_src else "Contract is not open-source verified on DexTools.",
                    source="dextools",
                )
            )

        honeypot = _parse_yes_no_bool(data.get("isHoneypot"))
        if honeypot is not None:
            risk_summary.is_honeypot = bool(risk_summary.is_honeypot or honeypot)
            flags.append(
                NormalizedSecurityFlag(
                    code="dextools_honeypot",
                    title="Honeypot check (DexTools)",
                    category="contract",
                    severity="critical" if honeypot else "ok",
                    status="danger" if honeypot else "safe",
                    value=honeypot,
                    description="DexTools detected honeypot behavior!" if honeypot else "No honeypot detected by DexTools.",
                    source="dextools",
                )
            )

        mintable = _parse_yes_no_bool(data.get("isMintable"))
        if mintable is not None and authorities.mint_authority_active is None:
            authorities.mint_authority_active = mintable

        proxy = _parse_yes_no_bool(data.get("isProxy"))
        if proxy is not None:
            authorities.is_proxy = proxy

        renounced = _parse_yes_no_bool(data.get("isContractRenounced"))
        if renounced is not None:
            authorities.is_contract_renounced = renounced

        slippage_mod = _parse_yes_no_bool(data.get("slippageModifiable"))
        if slippage_mod is not None:
            verification.slippage_modifiable = slippage_mod

        blacklisted = _parse_yes_no_bool(data.get("isBlacklisted"))
        if blacklisted is not None:
            verification.is_blacklisted = blacklisted
            if blacklisted:
                flags.append(
                    NormalizedSecurityFlag(
                        code="dextools_blacklist",
                        title="Blacklist capability",
                        category="contract",
                        severity="high",
                        status="danger",
                        value=True,
                        description="DexTools reports a blacklist function on this token.",
                        source="dextools",
                    )
                )

        scam_flag = _parse_yes_no_bool(data.get("isPotentiallyScam"))
        if scam_flag is not None:
            verification.is_potentially_scam = scam_flag
            if scam_flag:
                flags.append(
                    NormalizedSecurityFlag(
                        code="dextools_scam_warning",
                        title="Potential scam flag (DexTools)",
                        category="contract",
                        severity="critical",
                        status="danger",
                        value=True,
                        description="DexTools flags this token as potentially a scam.",
                        source="dextools",
                    )
                )

        for tax_key, target_attr in (("buyTax", "buy_tax_pct"), ("sellTax", "sell_tax_pct")):
            tax_val = data.get(tax_key)
            if isinstance(tax_val, dict):
                max_tax = _safe_non_negative_float(tax_val.get("max") if tax_val.get("max") is not None else tax_val.get("min"))
                if max_tax is not None:
                    setattr(verification, target_attr, max_tax)
            else:
                direct_tax = _safe_non_negative_float(tax_val)
                if direct_tax is not None:
                    setattr(verification, target_attr, direct_tax)

        dext_score = data.get("dextScore")
        if isinstance(dext_score, dict):
            tot = _safe_non_negative_float(dext_score.get("total"))
            if tot is not None:
                verification.dextools_score = min(100.0, tot)
        else:
            tot = _safe_non_negative_float(dext_score)
            if tot is not None:
                verification.dextools_score = min(100.0, tot)

        dt_holders = _safe_int(
            data.get("holders") if "holders" in data else data.get("holdersCount")
        )
        if dt_holders is not None and holders.holder_count is None:
            holders.holder_count = dt_holders

    def _apply_gmgn_data(
        self,
        data: dict[str, Any],
        *,
        authorities: ContractAuthorities,
        holders: HolderDistribution,
        liquidity: LiquiditySecurity,
        verification: TokenVerificationMetadata,
        risk_summary: SecurityRiskSummary,
        flags: list[NormalizedSecurityFlag],
    ) -> None:
        honeypot = _parse_yes_no_bool(data.get("is_honeypot") if "is_honeypot" in data else data.get("honeypot"))
        if honeypot is not None:
            risk_summary.is_honeypot = bool(risk_summary.is_honeypot or honeypot)
            flags.append(
                NormalizedSecurityFlag(
                    code="gmgn_honeypot",
                    title="GMGN honeypot check",
                    category="contract",
                    severity="critical" if honeypot else "ok",
                    status="danger" if honeypot else "safe",
                    value=honeypot,
                    description="GMGN Agent API reports honeypot risk." if honeypot else "GMGN Agent API reports no honeypot.",
                    source="gmgn",
                )
            )

        renounced_mint = _parse_yes_no_bool(data.get("renounced_mint"))
        if renounced_mint is not None and authorities.mint_authority_active is None:
            authorities.mint_authority_active = not renounced_mint

        renounced_freeze = _parse_yes_no_bool(data.get("renounced_freeze_account"))
        if renounced_freeze is not None and authorities.freeze_authority_active is None:
            authorities.freeze_authority_active = not renounced_freeze

        burn_ratio = _safe_non_negative_float(data.get("burn_ratio"))
        if burn_ratio is not None:
            pct = burn_ratio * 100.0 if burn_ratio <= 1.0 else burn_ratio
            liquidity.lp_burned_pct = round(min(100.0, pct), 2)
            flags.append(
                NormalizedSecurityFlag(
                    code="gmgn_lp_burn",
                    title="LP burned ratio (GMGN)",
                    category="liquidity",
                    severity="ok" if liquidity.lp_burned_pct >= 80 else "warn",
                    status="safe" if liquidity.lp_burned_pct >= 80 else "warning",
                    value=liquidity.lp_burned_pct,
                    description=f"GMGN reports {liquidity.lp_burned_pct:.2f}% LP burned.",
                    source="gmgn",
                )
            )

        top10 = _safe_non_negative_float(data.get("top_10_holder_rate"))
        if top10 is not None and holders.top_10_holders_pct is None:
            pct = top10 * 100.0 if top10 <= 1.0 else top10
            holders.top_10_holders_pct = round(min(100.0, pct), 2)

        creator_pct = _safe_non_negative_float(
            data.get("creator_percent") if "creator_percent" in data else data.get("creator_balance_rate")
        )
        if creator_pct is not None and holders.creator_balance_pct is None:
            pct = creator_pct * 100.0 if creator_pct <= 1.0 else creator_pct
            holders.creator_balance_pct = round(min(100.0, pct), 2)

        bundler_rate = _safe_non_negative_float(
            data.get("bundler_rate") if "bundler_rate" in data else data.get("bundled_supply_pct")
        )
        if bundler_rate is not None:
            pct = bundler_rate * 100.0 if bundler_rate <= 1.0 else bundler_rate
            holders.bundled_supply_pct = round(min(100.0, pct), 2)
            flags.append(
                NormalizedSecurityFlag(
                    code="gmgn_bundler_rate",
                    title="Bundled supply ratio (GMGN)",
                    category="insiders",
                    severity="high" if holders.bundled_supply_pct >= 25 else "warn" if holders.bundled_supply_pct >= 10 else "ok",
                    status="danger" if holders.bundled_supply_pct >= 25 else "warning" if holders.bundled_supply_pct >= 10 else "safe",
                    value=holders.bundled_supply_pct,
                    description=f"GMGN reports {holders.bundled_supply_pct:.2f}% bundled transaction supply.",
                    source="gmgn",
                )
            )

        sniper_cnt = _safe_int(data.get("sniper_count"))
        if sniper_cnt is not None:
            holders.sniper_holders_count = sniper_cnt
        sniper_rate = _safe_non_negative_float(data.get("sniper_hold_rate"))
        if sniper_rate is not None:
            pct = sniper_rate * 100.0 if sniper_rate <= 1.0 else sniper_rate
            holders.sniper_supply_pct = round(min(100.0, pct), 2)

        dev_rugs = _safe_int(
            data.get("dev_rug_history_count")
            if "dev_rug_history_count" in data
            else data.get("rug_count")
        )
        if dev_rugs is not None:
            holders.dev_rug_history_count = dev_rugs

        gmgn_holders = _safe_int(data.get("holder_count"))
        if gmgn_holders is not None and holders.holder_count is None:
            holders.holder_count = gmgn_holders

        buy_tax = _safe_non_negative_float(data.get("buy_tax"))
        if buy_tax is not None and verification.buy_tax_pct is None:
            verification.buy_tax_pct = round(buy_tax * 100.0 if buy_tax <= 1.0 and buy_tax > 0 else buy_tax, 2)
        sell_tax = _safe_non_negative_float(data.get("sell_tax"))
        if sell_tax is not None and verification.sell_tax_pct is None:
            verification.sell_tax_pct = round(sell_tax * 100.0 if sell_tax <= 1.0 and sell_tax > 0 else sell_tax, 2)

    def _build_normalized_flags(
        self,
        *,
        authorities: ContractAuthorities,
        holders: HolderDistribution,
        liquidity: LiquiditySecurity,
        activity: ExtendedMarketActivity,
        verification: TokenVerificationMetadata,
        risk_summary: SecurityRiskSummary,
        flags: list[NormalizedSecurityFlag],
    ) -> dict[str, bool | None]:
        lp_effective_lock = max(
            [
                v
                for v in (liquidity.lp_locked_pct, liquidity.lp_burned_pct)
                if v is not None
            ],
            default=None,
        )
        max_fee = max(
            [
                v
                for v in (
                    authorities.transfer_fee_pct,
                    verification.buy_tax_pct,
                    verification.sell_tax_pct,
                )
                if v is not None
            ],
            default=None,
        )
        liq_usd = (
            liquidity.total_market_liquidity_usd
            if liquidity.total_market_liquidity_usd is not None
            else activity.liquidity_usd
        )
        return {
            "mint_authority_enabled": authorities.mint_authority_active,
            "freeze_authority_enabled": authorities.freeze_authority_active,
            "mutable_metadata": authorities.mutable_metadata,
            "lp_not_locked": (lp_effective_lock < 50.0)
            if lp_effective_lock is not None
            else None,
            "high_holder_concentration": (holders.top_10_holders_pct >= 50.0)
            if holders.top_10_holders_pct is not None
            else None,
            "single_holder_dominance": (holders.top_holder_pct >= 20.0)
            if holders.top_holder_pct is not None
            else None,
            "creator_holds_significant_supply": (holders.creator_balance_pct >= 10.0)
            if holders.creator_balance_pct is not None
            else None,
            "honeypot_detected": risk_summary.is_honeypot,
            "high_tax_or_fee": (max_fee >= 5.0) if max_fee is not None else None,
            "rugged_token": risk_summary.rugged,
            "insider_activity_detected": (
                (holders.insider_networks_count or 0) > 0
                or (holders.insider_holders_count or 0) > 0
            )
            if (
                holders.insider_networks_count is not None
                or holders.insider_holders_count is not None
            )
            else None,
            "bundled_launch_detected": (holders.bundled_supply_pct >= 10.0)
            if holders.bundled_supply_pct is not None
            else None,
            "low_liquidity_warning": (liq_usd < 10000.0)
            if liq_usd is not None
            else None,
        }

    def _finalize_risk_summary(
        self,
        *,
        risk_summary: SecurityRiskSummary,
        authorities: ContractAuthorities,
        holders: HolderDistribution,
        liquidity: LiquiditySecurity,
        verification: TokenVerificationMetadata,
        flags: list[NormalizedSecurityFlag],
        sources: dict[SecuritySourceName, SecuritySourceStatus],
    ) -> None:
        critical_count = sum(1 for f in flags if f.severity in {"critical", "high"})
        warning_count = sum(1 for f in flags if f.severity in {"warn", "low"})
        safe_count = sum(1 for f in flags if f.severity == "ok")

        risk_summary.total_flags_count = len(flags)
        risk_summary.critical_flags_count = critical_count
        risk_summary.warning_flags_count = warning_count
        risk_summary.safe_flags_count = safe_count

        if risk_summary.normalized_score is None and any(
            s.status == "ok" for s in sources.values()
        ):
            computed = 0.0
            if risk_summary.rugged or risk_summary.is_honeypot:
                computed += 85.0
            if authorities.mint_authority_active:
                computed += 30.0
            if authorities.freeze_authority_active:
                computed += 20.0
            if authorities.mutable_metadata:
                computed += 10.0
            if holders.top_10_holders_pct is not None and holders.top_10_holders_pct >= 50:
                computed += 20.0
            if liquidity.lp_locked_pct is not None and liquidity.lp_locked_pct < 50:
                computed += 15.0
            if flags:
                risk_summary.normalized_score = round(min(100.0, computed), 2)
                risk_summary.safety_score = round(max(0.0, 100.0 - risk_summary.normalized_score), 2)

        if risk_summary.rugged or risk_summary.is_honeypot:
            risk_summary.risk_level = "critical"
        elif risk_summary.normalized_score is not None:
            score = risk_summary.normalized_score
            if score >= 75:
                risk_summary.risk_level = "critical"
            elif score >= 50:
                risk_summary.risk_level = "high"
            elif score >= 25:
                risk_summary.risk_level = "medium"
            else:
                risk_summary.risk_level = "low"
        elif critical_count > 0:
            risk_summary.risk_level = "high"
        elif warning_count > 0:
            risk_summary.risk_level = "medium"
        elif safe_count > 0:
            risk_summary.risk_level = "low"
        else:
            risk_summary.risk_level = "unknown"

        ok_sources = [name for name, s in sources.items() if s.status == "ok"]
        unavail_sources = [name for name, s in sources.items() if s.status == "unavailable"]
        if not ok_sources:
            risk_summary.verdict_summary = (
                "Security data sources are currently unavailable or returned no data for this token."
            )
        else:
            parts = [
                f"Aggregated from {', '.join(ok_sources)} ({critical_count} critical/high, {warning_count} warning, {safe_count} safe signals)."
            ]
            if unavail_sources:
                parts.append(
                    f"Unavailable sources ({', '.join(unavail_sources)}) are marked explicitly and not treated as safe."
                )
            risk_summary.verdict_summary = " ".join(parts)


def get_security_client(request: Request) -> Iterator[SecurityDataClient]:
    settings: Settings = getattr(request.app.state, "settings", Settings.from_env())
    # When unit tests override only get_dexscreener_client, avoid live network requests.
    if (
        get_dexscreener_client in request.app.dependency_overrides
        and get_security_client not in request.app.dependency_overrides
    ):
        transport = httpx.MockTransport(
            lambda req: httpx.Response(503, json={"detail": "offline_test_transport"})
        )
        with httpx.Client(transport=transport, timeout=10.0) as offline_client:
            yield SecurityDataClient(
                offline_client,
                rugcheck_api_key=settings.rugcheck_api_key,
                dextools_api_key=getattr(settings, "dextools_api_key", None),
                gmgn_api_key=settings.gmgn_api_key,
            )
        return

    with httpx.Client(timeout=10.0) as client:
        yield SecurityDataClient(
            client,
            rugcheck_api_key=settings.rugcheck_api_key,
            dextools_api_key=getattr(settings, "dextools_api_key", None),
            gmgn_api_key=settings.gmgn_api_key,
        )
