from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.market_data import (
    DexScreenerClient,
    MarketDataError,
    MarketDataTimeout,
    TokenMarketData,
    get_dexscreener_client,
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
    market_data: TokenMarketData


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
) -> TokenReportResponse:
    try:
        market_data = provider.fetch_token_market(payload.address)
    except MarketDataTimeout as error:
        raise HTTPException(status_code=504, detail="MARKET_DATA_TIMEOUT") from error
    except MarketDataError as error:
        raise HTTPException(status_code=502, detail="MARKET_DATA_UNAVAILABLE") from error

    return TokenReportResponse(
        id=str(uuid4()),
        subject_type="token",
        address=payload.address,
        created_at=datetime.now(timezone.utc),
        disclaimer="Analiza ma charakter informacyjny i wymaga wlasnej weryfikacji.",
        market_data=market_data,
    )


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
