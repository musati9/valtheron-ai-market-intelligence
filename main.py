import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Valtheron AI Market Intelligence")

API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")

ASSETS = {
    "EURUSD": {
        "name": "EUR/USD",
        "function": "FX_DAILY",
        "from_symbol": "EUR",
        "to_symbol": "USD",
    },
    "GBPUSD": {
        "name": "GBP/USD",
        "function": "FX_DAILY",
        "from_symbol": "GBP",
        "to_symbol": "USD",
    },
    "USDJPY": {
        "name": "USD/JPY",
        "function": "FX_DAILY",
        "from_symbol": "USD",
        "to_symbol": "JPY",
    },
    "AAPL": {
        "name": "Apple",
        "function": "TIME_SERIES_DAILY",
        "symbol": "AAPL",
    },
    "BTC": {
        "name": "Bitcoin",
        "function": "DIGITAL_CURRENCY_DAILY",
        "symbol": "BTC",
    },
    "ETH": {
        "name": "Ethereum",
        "function": "DIGITAL_CURRENCY_DAILY",
        "symbol": "ETH",
    },
}


@app.get("/health")
async def health():
    return {
        "status": "online",
        "application": "Valtheron AI Market Intelligence",
        "api_key_configured": bool(API_KEY),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/watchlist")
async def watchlist():
    return [
        {"symbol": symbol, "name": asset["name"]}
        for symbol, asset in ASSETS.items()
    ]


@app.get("/api/market/{symbol}")
async def get_market(symbol: str):
    symbol = symbol.upper()

    if symbol not in ASSETS:
        return {
            "status": "unavailable",
            "error": "Unsupported market symbol.",
        }

    if not API_KEY:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "error": "Market-data API key is not configured.",
        }

    asset = ASSETS[symbol]

    params = {
        "function": asset["function"],
        "apikey": API_KEY,
    }

    if asset["function"] == "FX_DAILY":
        params["from_symbol"] = asset["from_symbol"]
        params["to_symbol"] = asset["to_symbol"]

    elif asset["function"] == "TIME_SERIES_DAILY":
        params["symbol"] = asset["symbol"]

    else:
        params["symbol"] = asset["symbol"]
        params["market"] = "USD"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://www.alphavantage.co/query",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        if data.get("Note") or data.get("Information"):
            return {
                "status": "unavailable",
                "symbol": symbol,
                "error": (
                    data.get("Note")
                    or data.get("Information")
                ),
            }

        if data.get("Error Message"):
            return {
                "status": "unavailable",
                "symbol": symbol,
                "error": data["Error Message"],
            }

        series_key = next(
            (
                key
                for key in data
                if "Time Series" in key
            ),
            None,
        )

        if not series_key:
            return {
                "status": "unavailable",
                "symbol": symbol,
                "error": "No market time series was returned.",
            }

        series = sorted(
            data[series_key].items(),
            reverse=True,
        )

        latest_date, latest = series[0]

        if len(series) > 1:
            previous = series[1][1]
        else:
            previous = latest

        close_key = next(
            (
                key
                for key in latest
                if "close" in key.lower()
                and (
                    "usd" not in key.lower()
                    or symbol in ("BTC", "ETH")
                )
            ),
            "4. close",
        )

        # Crypto responses may use currency-specific field names.
        if close_key not in latest:
            close_key = next(
                key for key in latest
                if "close" in key.lower()
            )

        price = float(latest[close_key])

        previous_close_key = next(
            (
                key for key in previous
                if "close" in key.lower()
                and (
                    "usd" not in key.lower()
                    or symbol in ("BTC", "ETH")
                )
            ),
            close_key,
        )

        if previous_close_key not in previous:
            previous_close_key = next(
                key for key in previous
                if "close" in key.lower()
            )

        previous_price = float(
            previous[previous_close_key]
        )

        change_pct = (
            (price - previous_price) / previous_price * 100
            if previous_price
            else 0
        )

        return {
            "status": "ok",
            "symbol": symbol,
            "name": asset["name"],
            "price": price,
            "previous_close": previous_price,
            "change_percent": round(change_pct, 3),
            "candle_date": latest_date,
            "provider": "Alpha Vantage",
            "is_realtime": False,
            "checked_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    except Exception as exc:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "error": str(exc),
        }


@app.get("/api/analyze/{symbol}")
async def analyze_market(symbol: str):
    result = await get_market(symbol)

    if result.get("status") != "ok":
        return {
            "status": "unavailable",
            "summary": (
                "Analysis paused because valid "
                "market data is unavailable."
            ),
            "market_data": result,
        }

    change = result["change_percent"]

    if change > 0.25:
        bias = "Positive daily momentum"
    elif change < -0.25:
        bias = "Negative daily momentum"
    else:
        bias = "Mixed daily momentum"

    return {
        "status": "ok",
        "symbol": result["symbol"],
        "bias": bias,
        "summary": (
            f'{result["name"]} has a latest available '
            f'daily close of {result["price"]}. '
            f'The change versus the previous daily close '
            f'is {change:.3f}%.'
        ),
        "evidence": {
            "candle_date": result["candle_date"],
            "data_provider": result["provider"],
        },
        "limitations": [
            "This is preliminary rules-based analysis.",
            "Daily data is not a live trading quote.",
            "No trading outcome is guaranteed.",
        ],
}
@app.get("/", response_class=HTMLResponse)
async def home():
    with open("static/index.html", encoding="utf-8") as file:
        return file.read()
