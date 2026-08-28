"""Parser SEC companyfacts -> znormalizowane wiersze faktow.

Struktura zrodlowa:

    facts["us-gaap"]["Revenues"]["units"]["USD"] = [
        {"start": "2018-01-01", "end": "2018-03-31", "val": 61137000000,
         "accn": "0000320193-18-000070", "fy": 2018, "fp": "Q2",
         "form": "10-Q", "filed": "2018-05-02", "frame": "CY2018Q1"},
        ...
    ]

Ta sama wartosc (cik, tag, period_end) pojawia sie WIELOKROTNIE, raz na
kazde zlozenie, w ktorym byla raportowana - w tym w korektach i w
kolejnych raportach jako dane porownawcze. Rozniace sie `accn` i `filed`
to nie duplikaty do usuniecia. To jest historia wiedzy rynku i caly powod,
dla ktorego uzywamy SEC zamiast platnego API.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any, Iterator

log = logging.getLogger(__name__)

# Tagi wystarczajace do metryk Fazy 1. Swiadomie waskie - kazdy dodatkowy
# tag to dodatkowy koszt walidacji na golden set (T3-T4).
CORE_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cogs": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "ocf": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_debt": ("ShortTermBorrowings", "LongTermDebtCurrent"),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "operating_lease_liab_current": ("OperatingLeaseLiabilityCurrent",),
    "operating_lease_liab_noncurrent": ("OperatingLeaseLiabilityNoncurrent",),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "shares_outstanding": ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"),
    "tax_expense": ("IncomeTaxExpenseBenefit",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "interest_expense": ("InterestExpense", "InterestExpenseDebt"),
}

_ALL_CORE_TAGS = {tag for tags in CORE_TAGS.values() for tag in tags}


@dataclass(frozen=True, slots=True)
class Fact:
    cik: int
    taxonomy: str
    tag: str
    unit: str
    value: float | None
    period_start: date | None
    period_end: date
    fy: int | None
    fp: str | None
    form: str | None
    filed_date: date
    accession: str
    frame: str | None

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        log.warning("Nieparsowalna data: %r", raw)
        return None


def parse_company_facts(
    payload: dict[str, Any],
    tags: set[str] | None = None,
    taxonomies: tuple[str, ...] = ("us-gaap", "dei", "ifrs-full"),
) -> Iterator[Fact]:
    """Splaszcza companyfacts do strumienia obiektow Fact.

    tags=None -> tylko CORE_TAGS. Podaj set(), zeby pobrac wszystko
    (ostrzezenie: dla duzej spolki to setki tysiecy wierszy).
    """
    cik = int(payload["cik"])
    wanted = _ALL_CORE_TAGS if tags is None else tags
    facts = payload.get("facts", {})

    for taxonomy in taxonomies:
        for tag, tag_body in facts.get(taxonomy, {}).items():
            if wanted and tag not in wanted:
                continue
            for unit, entries in tag_body.get("units", {}).items():
                for entry in entries:
                    filed = _parse_date(entry.get("filed"))
                    end = _parse_date(entry.get("end"))
                    accession = entry.get("accn")
                    # filed_date i accession sa fundamentem PIT. Bez nich
                    # fakt jest bezuzyteczny i lepiej go odrzucic niz
                    # zgadywac date.
                    if filed is None or end is None or not accession:
                        continue
                    yield Fact(
                        cik=cik,
                        taxonomy=taxonomy,
                        tag=tag,
                        unit=unit,
                        value=entry.get("val"),
                        period_start=_parse_date(entry.get("start")),
                        period_end=end,
                        fy=entry.get("fy"),
                        fp=entry.get("fp"),
                        form=entry.get("form"),
                        filed_date=filed,
                        accession=accession,
                        frame=entry.get("frame"),
                    )


def extract_company_meta(submissions: dict[str, Any]) -> dict[str, Any]:
    """Metadane spolki z endpointu submissions (SIC, exchange, tickery)."""
    tickers = submissions.get("tickers") or []
    exchanges = submissions.get("exchanges") or []
    return {
        "cik": int(submissions["cik"]),
        "name": submissions.get("name"),
        "sic": submissions.get("sic"),
        "sic_description": submissions.get("sicDescription"),
        "tickers": tickers,
        "primary_ticker": tickers[0] if tickers else None,
        "exchange": exchanges[0] if exchanges else None,
        "fiscal_year_end": submissions.get("fiscalYearEnd"),
    }
