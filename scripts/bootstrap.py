"""Ingest end-to-end dla kilku tickerow.

    python scripts/bootstrap.py AAPL MSFT NVDA
    python scripts/bootstrap.py AAPL --as-of 2020-06-01 --report

Bez --prices nie dotyka EODHD (oszczedza limit darmowego tieru).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from data_layer.db.connection import connect  # noqa: E402
from data_layer.sec.edgar_client import EdgarClient  # noqa: E402
from data_layer.sec.facts_repo import FactsRepository  # noqa: E402
from data_layer.sec.xbrl_parser import (  # noqa: E402
    extract_company_meta,
    parse_company_facts,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bootstrap")


def ingest_ticker(client: EdgarClient, repo: FactsRepository, ticker: str) -> int | None:
    try:
        cik = client.resolve_cik(ticker)
    except KeyError as exc:
        log.error("%s: %s", ticker, exc)
        return None

    meta = extract_company_meta(client.submissions(cik))
    repo.con.execute(
        """
        INSERT INTO securities (cik, ticker, name, exchange, sic, is_active, source)
        VALUES (?,?,?,?,?,TRUE,'sec')
        ON CONFLICT DO NOTHING
        """,
        [cik, ticker.upper(), meta["name"], meta["exchange"], meta["sic"]],
    )

    n = repo.upsert_facts(parse_company_facts(client.company_facts(cik)))
    log.info("%s (CIK %s, SIC %s): %d faktow", ticker, cik, meta["sic"], n)
    return cik


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--as-of", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=date.today(), help="Data odciecia dla raportu pokrycia")
    ap.add_argument("--report", action="store_true", help="Pokaz raport pokrycia danych")
    ap.add_argument("--prices", action="store_true", help="Pobierz rowniez ceny z EODHD")
    ap.add_argument("--price-start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=date(2015, 1, 1))
    args = ap.parse_args()

    con = connect()
    repo = FactsRepository(con)
    client = EdgarClient()

    resolved: dict[str, int] = {}
    for t in args.tickers:
        cik = ingest_ticker(client, repo, t)
        if cik:
            resolved[t.upper()] = cik

    if args.prices:
        from data_layer.prices.eodhd_client import EODHDClient, price_rows, write_prices

        eod = EODHDClient()
        for t in resolved:
            rows = price_rows(t, eod.eod_prices(t, start=args.price_start))
            log.info("%s: %d wierszy cenowych", t, write_prices(con, rows))

    if args.report:
        for t, cik in resolved.items():
            print(f"\n=== {t} — stan wiedzy na {args.as_of} ===")
            for concept, status in repo.coverage_report(cik, args.as_of).items():
                mark = "OK " if status.startswith("OK") else "!! "
                print(f"  {mark}{concept:34s} {status}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
