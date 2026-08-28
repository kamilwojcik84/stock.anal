"""Klient SEC EDGAR.

Dlaczego SEC, a nie platny dostawca: endpoint companyfacts zwraca przy
kazdej wartosci pole `filed`. To daje point-in-time ZA DARMO. Platni
dostawcy w przedziale $20-60/mies. zwracaja dzisiejszy, skorygowany stan
sprawozdan - czyli maja look-ahead bias wbudowany w zrodlo, ktorego zadna
warstwa kodu nie naprawi.

SEC wymaga naglowka User-Agent z kontaktem i limituje do ~10 req/s.
Naruszenie konczy sie blokada IP, wiec limiter nie jest opcjonalny.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"

# Konserwatywnie ponizej limitu SEC (10/s). Nie ma powodu jechac po bandzie.
_MAX_REQUESTS_PER_SECOND = 6.0
_MIN_INTERVAL = 1.0 / _MAX_REQUESTS_PER_SECOND


class RateLimiter:
    """Prosty limiter odstepu miedzy zadaniami, bezpieczny watkowo."""

    def __init__(self, min_interval: float = _MIN_INTERVAL) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


class EdgarClient:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: str | Path | None = None,
        max_retries: int = 3,
    ) -> None:
        ua = user_agent or os.getenv("SEC_USER_AGENT")
        if not ua or "@" not in ua:
            raise ValueError(
                "SEC wymaga naglowka User-Agent w formacie 'Imie Nazwisko email@domena'. "
                "Ustaw SEC_USER_AGENT w .env. Bez tego SEC zwraca 403."
            )
        self.user_agent = ua
        self.cache_dir = Path(
            cache_dir or os.getenv("SEC_CACHE_DIR")
            or Path(__file__).resolve().parents[2] / "data" / "raw" / "sec"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._limiter = RateLimiter()
        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        )

    # -- transport ----------------------------------------------------
    def _get_json(self, url: str) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._limiter.wait()
            try:
                resp = self._session.get(url, timeout=30)
                if resp.status_code == 404:
                    raise FileNotFoundError(f"SEC 404: {url}")
                if resp.status_code == 429:
                    backoff = 2**attempt
                    log.warning("SEC 429, backoff %ss", backoff)
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp.json()
            except FileNotFoundError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("SEC request failed (%s/%s): %s", attempt + 1, self.max_retries, exc)
                time.sleep(2**attempt)
        raise RuntimeError(f"SEC request failed after {self.max_retries} attempts: {url}") from last_exc

    # -- cache --------------------------------------------------------
    def _cache_path(self, kind: str, key: str) -> Path:
        d = self.cache_dir / kind
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.json.gz"

    @staticmethod
    def _read_cache(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:  # noqa: BLE001
            log.warning("Uszkodzony cache %s: %s", path, exc)
            return None

    @staticmethod
    def _write_cache(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(path)

    # -- API ----------------------------------------------------------
    def company_facts(self, cik: int, force_refresh: bool = False) -> dict[str, Any]:
        """Pelny zestaw faktow XBRL spolki, z data zlozenia przy kazdej wartosci."""
        key = f"CIK{int(cik):010d}"
        path = self._cache_path("companyfacts", key)
        if not force_refresh:
            cached = self._read_cache(path)
            if cached is not None:
                log.debug("cache hit companyfacts %s", key)
                return cached
        payload = self._get_json(f"{SEC_DATA_BASE}/api/xbrl/companyfacts/{key}.json")
        payload["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        self._write_cache(path, payload)
        return payload

    def submissions(self, cik: int, force_refresh: bool = False) -> dict[str, Any]:
        """Metadane spolki + historia zlozonych formularzy (SIC, exchange, tickery)."""
        key = f"CIK{int(cik):010d}"
        path = self._cache_path("submissions", key)
        if not force_refresh:
            cached = self._read_cache(path)
            if cached is not None:
                return cached
        payload = self._get_json(f"{SEC_DATA_BASE}/submissions/{key}.json")
        payload["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        self._write_cache(path, payload)
        return payload

    def ticker_map(self, force_refresh: bool = False) -> dict[str, Any]:
        """Mapowanie ticker <-> CIK <-> exchange.

        UWAGA: ten plik zawiera wylacznie AKTYWNE spolki. Uniwersum
        zdelistowanych bierzemy z EODHD. Uzycie samego SEC jako zrodla
        uniwersum wprowadza survivorship bias.
        """
        path = self._cache_path("meta", "company_tickers_exchange")
        if not force_refresh:
            cached = self._read_cache(path)
            if cached is not None:
                return cached
        payload = self._get_json(f"{SEC_WWW_BASE}/files/company_tickers_exchange.json")
        payload["_fetched_at"] = datetime.now(timezone.utc).isoformat()
        self._write_cache(path, payload)
        return payload

    def resolve_cik(self, ticker: str) -> int:
        mapping = self.ticker_map()
        fields = mapping["fields"]
        i_cik, i_tic = fields.index("cik"), fields.index("ticker")
        target = ticker.strip().upper()
        for row in mapping["data"]:
            if str(row[i_tic]).upper() == target:
                return int(row[i_cik])
        raise KeyError(
            f"Ticker {ticker!r} nie znaleziony w aktywnym mapowaniu SEC. "
            "Jesli spolka jest zdelistowana, potrzebny jest CIK z innego zrodla."
        )
