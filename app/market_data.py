from datetime import datetime, timezone
from typing import Annotated, Iterator, Literal

import httpx
from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter


def normalize_optional_number(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool):
        raise ValueError("A market metric must be a number")
    return value


OptionalNumber = Annotated[
    Annotated[float, Field(allow_inf_nan=False)] | None,
    BeforeValidator(normalize_optional_number),
]
OptionalAmount = Annotated[
    Annotated[float, Field(ge=0, allow_inf_nan=False)] | None,
    BeforeValidator(normalize_optional_number),
]


class MarketToken(BaseModel):
    address: str
    name: str | None = None
    symbol: str | None = None


class MarketMetrics(BaseModel):
    price_usd: OptionalAmount = None
    liquidity_usd: OptionalAmount = None
    volume_24h_usd: OptionalAmount = None
    price_change_24h_percent: OptionalNumber = None


class MarketPair(MarketMetrics):
    chain_id: str
    dex_id: str
    pair_address: str
    url: str | None = None
    base_token: MarketToken
    quote_token: MarketToken


class TokenMarketData(MarketMetrics):
    source: Literal["dexscreener"] = "dexscreener"
    source_url: str
    updated_at: datetime
    status: Literal["ok", "no_data"]
    primary_pair_address: str | None = None
    pairs: list[MarketPair]


class _Liquidity(BaseModel):
    usd: OptionalAmount = None


class _Volume(BaseModel):
    h24: OptionalAmount = None


class _PriceChange(BaseModel):
    h24: OptionalNumber = None


class _DexScreenerPair(BaseModel):
    chain_id: str = Field(alias="chainId")
    dex_id: str = Field(alias="dexId")
    pair_address: str = Field(alias="pairAddress")
    url: str | None = None
    base_token: MarketToken = Field(alias="baseToken")
    quote_token: MarketToken = Field(alias="quoteToken")
    price_usd: OptionalAmount = Field(default=None, alias="priceUsd")
    liquidity: _Liquidity | None = None
    volume: _Volume | None = None
    price_change: _PriceChange | None = Field(default=None, alias="priceChange")


class MarketDataError(Exception):
    pass


class MarketDataTimeout(MarketDataError):
    pass


class DexScreenerClient:
    BASE_URL = "https://api.dexscreener.com/token-pairs/v1/solana"

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def fetch_token_market(self, address: str) -> TokenMarketData:
        source_url = f"{self.BASE_URL}/{address}"
        try:
            response = self.client.get(source_url)
            response.raise_for_status()
            source_pairs = TypeAdapter(list[_DexScreenerPair] | None).validate_python(
                response.json()
            )
        except httpx.TimeoutException as error:
            raise MarketDataTimeout("DexScreener request timed out") from error
        except (httpx.HTTPError, ValueError) as error:
            raise MarketDataError("DexScreener data is unavailable or invalid") from error

        pairs = [
            MarketPair(
                chain_id=pair.chain_id,
                dex_id=pair.dex_id,
                pair_address=pair.pair_address,
                url=pair.url,
                base_token=pair.base_token,
                quote_token=pair.quote_token,
                price_usd=pair.price_usd,
                liquidity_usd=pair.liquidity.usd if pair.liquidity else None,
                volume_24h_usd=pair.volume.h24 if pair.volume else None,
                price_change_24h_percent=(
                    pair.price_change.h24 if pair.price_change else None
                ),
            )
            for pair in source_pairs or []
            if pair.chain_id == "solana"
            and address in {pair.base_token.address, pair.quote_token.address}
        ]
        primary_pair = max(
            (pair for pair in pairs if pair.base_token.address == address),
            key=lambda pair: (
                pair.liquidity_usd is not None,
                pair.liquidity_usd if pair.liquidity_usd is not None else 0,
            ),
            default=None,
        )
        metrics = (
            MarketMetrics.model_validate(primary_pair.model_dump())
            if primary_pair
            else MarketMetrics()
        )
        return TokenMarketData(
            **metrics.model_dump(),
            source_url=source_url,
            updated_at=datetime.now(timezone.utc),
            status="ok" if pairs else "no_data",
            primary_pair_address=primary_pair.pair_address if primary_pair else None,
            pairs=pairs,
        )


def get_dexscreener_client() -> Iterator[DexScreenerClient]:
    with httpx.Client(timeout=10.0) as client:
        yield DexScreenerClient(client)
