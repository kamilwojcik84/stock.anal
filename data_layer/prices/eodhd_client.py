"""Klient EODHD - ceny EOD i lista symboli, w tym ZDELISTOWANYCH.

Flaga delisted=1 na exchange-symbol-list jest powodem, dla ktorego
placimy akurat temu dostawcy. Uniwersum zlozone wylacznie ze spolek
obecnie notowanych zawyza wyniki backtestu SYSTEMATYCZNIE, nie losowo -
wypadaja z niego bankructwa i wykupy po niskiej cenie.

Darmowy tier (20 wywolan/dobe, rok historii) wystarcza do zbudowania
i przetestowania tego modulu. Platny plan wlaczasz dopiero, gdy pipeline
dziala.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any, Iterable

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://eodhd.com/api"


class EODHDClient:
    def __init__(self, api_key: str | None = None, max_retries: int = 3) -> None:
        self.api_key = api_key or os.getenv("EODHD_API_KEY")
        if not self.api_key:
            raise ValueError("Brak EODHD_API_KEY. Ustaw w .env (patrz .env.example).")
        self.max_retries = max_retries
        self._session = requests.Session()

    def _get(self, path: str, **params: Any) -> Any:
        params.update({"api_token": self.api_key, "fmt": "json"})
        url = f"{BASE_URL}/{path}"
        for attempt in range(self.max_retries):
            try:
                resp = self._session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    time.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                log.warning("EODHD failed (%s/%s): %s", attempt + 1, self.max_retries, exc)
                time.sleep(2**attempt)
        raise RuntimeError(f"EODHD request failed: {url}")

    # -- uniwersum ----------------------------------------------------
    def exchange_symbols(
        self, exchange: str = "US", delisted: bool = False, security_type: str = "common_stock"
    ) -> list[dict[str, Any]]:
        return self._get(
            f"exchange-symbol-list/{exchange}",
            delisted=1 if delisted else 0,
            type=security_type,
        )

    def full_universe(self, exchange: str = "US") -> list[dict[str, Any]]:
        """Aktywne + zdelistowane. To jest jedyne uniwersum, na ktorym
        wolno backtestowac."""
        active = self.exchange_symbols(exchange, delisted=False)
        for row in active:
            row["_is_active"] = True
        dead = self.exchange_symbols(exchange, delisted=True)
        for row in dead:
            row["_is_active"] = False
        log.info("Uniwersum %s: %d aktywnych, %d zdelistowanych", exchange, len(active), len(dead))
        return active + dead

    # -- ceny ---------------------------------------------------------
    def eod_prices(
        self,
        ticker: str,
        start: date | None = None,
        end: date | None = None,
        exchange: str = "US",
    ) -> list[dict[str, Any]]:
        symbol = ticker if "." in ticker else f"{ticker}.{exchange}"
        params: dict[str, Any] = {"period": "d"}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        data = self._get(f"eod/{symbol}", **params)
        return data if isinstance(data, list) else []


def price_rows(ticker: str, payload: Iterable[dict[str, Any]], source: str = "eodhd") -> list[tuple]:
    """Mapuje odpowiedz EODHD na wiersze price_daily."""
    rows: list[tuple] = []
    for r in payload:
        if not r.get("date"):
            continue
        rows.append(
            (
                ticker.upper(),
                r["date"],
                r.get("open"),
                r.get("high"),
                r.get("low"),
                r.get("close"),
                r.get("adjusted_close"),
                int(r["volume"]) if r.get("volume") is not None else None,
                source,
            )
        )
    return rows


def write_prices(con, rows: list[tuple]) -> int:
    if not rows:
        return 0
    con.executemany(
        """
        INSERT INTO price_daily
            (ticker, date, open, high, low, close, adj_close, volume, source)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT DO NOTHING
        """,
        rows,
    )
    return len(rows)
