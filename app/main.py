from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Token AI API",
    version="0.1.0",
    description="API MVP do analizy adresow Solany. Wyniki sa przeslankami, nie porada inwestycyjna.",
)
app.state.settings = Settings.from_env()
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")


class AnalysisRequest(BaseModel):
    address: str = Field(min_length=32, max_length=64)


class AnalysisResponse(BaseModel):
    id: str
    subject_type: str
    address: str
    created_at: datetime
    disclaimer: str


def validate_solana_address(address: str) -> None:
    # Walidacja bazowego formatu bez wykonywania zadnego zapytania on-chain.
    base58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
    if not set(address).issubset(base58):
        raise HTTPException(status_code=422, detail="Adres musi miec format Base58 Solany.")


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


@app.post("/analyses/wallet", response_model=AnalysisResponse, status_code=201)
def analyse_wallet(payload: AnalysisRequest) -> AnalysisResponse:
    validate_solana_address(payload.address)
    return AnalysisResponse(
        id=str(uuid4()),
        subject_type="wallet",
        address=payload.address,
        created_at=datetime.now(timezone.utc),
        disclaimer="Analiza ma charakter informacyjny i wymaga wlasnej weryfikacji.",
    )


@app.post("/analyses/token", response_model=AnalysisResponse, status_code=201)
def analyse_token(payload: AnalysisRequest) -> AnalysisResponse:
    validate_solana_address(payload.address)
    return AnalysisResponse(
        id=str(uuid4()),
        subject_type="token",
        address=payload.address,
        created_at=datetime.now(timezone.utc),
        disclaimer="Analiza ma charakter informacyjny i wymaga wlasnej weryfikacji.",
    )
