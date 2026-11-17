from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.trading_activity import GmgnActivity, GmgnClient, get_gmgn_client
from app.config import Settings
from app.ai_analysis import AIAnalysisClient, AIAnalysisResult, get_ai_client
from app.local_research import LocalResearchClient, get_local_research_client
from app.listing_data import ListingClient, ListingStatus, get_listing_client
from app.market_data import (
    DexScreenerClient,
    MarketDataError,
    MarketDataTimeout,
    TokenMarketData,
    get_dexscreener_client,
)
from app.onchain_data import (
    SolscanClient,
    TokenOnChainData,
    get_solscan_client,
)
from app.security_data import (
    SecurityDataClient,
    TokenSecurityData,
    get_security_client,
)
from app.source_data import (
    DEFAULT_PROVIDER_TIMEOUT,
    SourceError,
    combine_token_sources,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Token AI API",
    version="0.1.0",
    description="API MVP do analizy adresow Solany. Wyniki sa przeslankami, nie porada inwestycyjna.",
)
app.state.settings = Settings.from_env()
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


def validate_solana_address(address: str) -> None:
    if not 32 <= len(address) <= 44:
        raise HTTPException(status_code=422, detail="INVALID_ADDRESS")

    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    decoded_value = 0
    for character in address:
        digit = alphabet.find(character)
        if digit == -1:
            raise HTTPException(status_code=422, detail="INVALID_ADDRESS")
        decoded_value = decoded_value * 58 + digit

    leading_zero_bytes = len(address) - len(address.lstrip("1"))
    decoded_length = leading_zero_bytes + (decoded_value.bit_length() + 7) // 8
    if decoded_length != 32:
        raise HTTPException(status_code=422, detail="INVALID_ADDRESS")


class AnalysisRequest(BaseModel):
    address: str = Field(
        min_length=32,
        max_length=44,
        description="Adres Solana w Base58, ktory po zdekodowaniu ma dokladnie 32 bajty.",
    )

    @field_validator("address")
    @classmethod
    def validate_address(cls, address: str) -> str:
        validate_solana_address(address)
        return address


class AnalysisResponse(BaseModel):
    id: str
    subject_type: str
    address: str
    created_at: datetime
    disclaimer: str


class TokenReportResponse(AnalysisResponse):
    status: Literal["ok", "partial", "no_data", "unavailable"] = "ok"
    partial: bool = False
    market_data: TokenMarketData
    gmgn_activity: GmgnActivity
    security_data: TokenSecurityData | None = None
    onchain_data: TokenOnChainData | None = None
    sources_status: dict[str, str] = Field(default_factory=dict)
    source_errors: list[SourceError] = Field(default_factory=list)
    errors: list[SourceError] = Field(default_factory=list)


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    if request.method == "POST" and request.url.path in {
        "/analyses/wallet",
        "/analyses/token",
    }:
        return JSONResponse(status_code=422, content={"detail": "INVALID_ADDRESS"})
    return await request_validation_exception_handler(request, error)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/client-config")
def client_config() -> dict[str, str]:
    """Expose only browser-safe configuration, never provider credentials."""
    return {"apiBaseUrl": app.state.settings.public_api_base_url}


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/analysis", include_in_schema=False)
def analysis_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "analysis.html")


@app.get("/token/{address}", include_in_schema=False)
def token_report_page(address: str) -> FileResponse:
    # Keep the address in the URL for direct visits and reloads.
    return FileResponse(FRONTEND_DIR / "token.html")


@app.post("/analyses/wallet", response_model=AnalysisResponse, status_code=201)
def analyse_wallet(payload: AnalysisRequest) -> AnalysisResponse:
    return AnalysisResponse(
        id=str(uuid4()),
        subject_type="wallet",
        address=payload.address,
        created_at=datetime.now(timezone.utc),
        disclaimer="Analiza ma charakter informacyjny i wymaga wlasnej weryfikacji.",
    )


@app.post("/analyses/token", response_model=TokenReportResponse, status_code=201)
def analyse_token(
    payload: AnalysisRequest,
    provider: DexScreenerClient = Depends(get_dexscreener_client),
    gmgn: GmgnClient = Depends(get_gmgn_client),
    security_provider: SecurityDataClient = Depends(get_security_client),
    solscan: SolscanClient = Depends(get_solscan_client),
    allow_partial: bool = False,
    provider_timeout: float | None = None,
) -> TokenReportResponse:
    effective_timeout = (
        provider_timeout
        if provider_timeout is not None
        else getattr(app.state.settings, "provider_timeout_seconds", DEFAULT_PROVIDER_TIMEOUT)
    )
    try:
        combined = combine_token_sources(
            payload.address,
            market_provider=provider,
            gmgn_provider=gmgn,
            security_provider=security_provider,
            solscan_provider=solscan,
            provider_timeout=effective_timeout,
            allow_partial=allow_partial,
        )
    except MarketDataError as error:
        timed_out = isinstance(error, MarketDataTimeout)
        raise HTTPException(
            status_code=504 if timed_out else 502,
            detail="MARKET_DATA_TIMEOUT" if timed_out else "MARKET_DATA_UNAVAILABLE",
        ) from error

    return TokenReportResponse(
        id=str(uuid4()),
        subject_type="token",
        address=payload.address,
        created_at=datetime.now(timezone.utc),
        disclaimer="Analiza ma charakter informacyjny i wymaga wlasnej weryfikacji.",
        status=combined.status,
        partial=combined.partial,
        market_data=combined.market_data,
        gmgn_activity=combined.gmgn_activity,
        security_data=combined.security_data,
        onchain_data=combined.onchain_data,
        sources_status=combined.sources_status,
        source_errors=combined.source_errors,
        errors=combined.source_errors,
    )


@app.get("/api/tokens/{address}/security", response_model=TokenSecurityData)
def get_token_security_report(
    address: str,
    security_provider: SecurityDataClient = Depends(get_security_client),
) -> TokenSecurityData:
    validate_solana_address(address)
    return security_provider.fetch_token_security(address)


@app.post("/api/tokens/{address}/ai-analysis", response_model=AIAnalysisResult)
def analyse_token_facts(
    address: str,
    security_provider: SecurityDataClient = Depends(get_security_client),
    ai: AIAnalysisClient = Depends(get_ai_client),
) -> AIAnalysisResult:
    validate_solana_address(address)
    report = security_provider.fetch_token_security(address)
    try:
        return ai.analyse(report.normalized_data, address=address)
    except TypeError:
        return ai.analyse(report.normalized_data)


@app.get("/api/tokens/{address}/ai-analysis", response_model=AIAnalysisResult)
def get_saved_token_ai_analysis(
    address: str,
    ai: AIAnalysisClient = Depends(get_ai_client),
) -> AIAnalysisResult:
    validate_solana_address(address)
    saved = ai.store.get_latest(address)
    if saved is None:
        return AIAnalysisResult(address=address, status="no_data")
    return saved


@app.get('/api/tokens/{address}/listing', response_model=ListingStatus)
def get_listing_status(address: str, provider: ListingClient = Depends(get_listing_client)) -> ListingStatus:
    validate_solana_address(address)
    return provider.fetch(address)


@app.get('/api/research-config')
def get_research_config() -> dict[str, str]:
    # Partner IDs are public domain identifiers, not API secrets.
    from os import environ
    return {'bubblemapsPartnerId': environ.get('BUBBLEMAPS_PARTNER_ID', 'demo').strip() or 'demo'}


@app.get('/api/tokens/{address}/local-research')
def get_local_research(address: str, provider: LocalResearchClient = Depends(get_local_research_client)) -> dict:
    validate_solana_address(address)
    return provider.fetch(address)


@app.get("/api/tokens/{address}/onchain", response_model=TokenOnChainData)
def get_token_onchain_report(
    address: str,
    solscan: SolscanClient = Depends(get_solscan_client),
) -> TokenOnChainData:
    validate_solana_address(address)
    return solscan.fetch_token_onchain(address)


class TokenAnalysisResponse(BaseModel):
    id: str
    status: str
    subject_type: str
    address: str
    created_at: datetime
    disclaimer: str


@app.exception_handler(RequestValidationError)
async def handle_token_analyses_validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    if request.method == "POST" and request.url.path == "/api/token-analyses":
        return JSONResponse(status_code=422, content={"detail": "INVALID_ADDRESS"})
    return await handle_request_validation_error(request, error)


@app.post("/api/token-analyses", response_model=TokenAnalysisResponse, status_code=202)
def start_token_analysis(payload: AnalysisRequest) -> TokenAnalysisResponse:
    return TokenAnalysisResponse(
        id=str(uuid4()),
        status="pending",
        subject_type="token",
        address=payload.address,
        created_at=datetime.now(timezone.utc),
        disclaimer="Analiza ma charakter informacyjny i wymaga wlasnej weryfikacji.",
    )
