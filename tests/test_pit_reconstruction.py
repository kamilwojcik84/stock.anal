"""BRAMKA FAZY 0.

Jesli te testy nie przechodza, nic innego w projekcie nie ma znaczenia -
kazdy backtest bedzie po cichu klamal.

Scenariusz oparty na najczestszym realnym przypadku: spolka raportuje
przychod za FY2019, a rok pozniej sklada korekte obnizajaca go o 10%.
System musi umiec odpowiedziec, co bylo wiadome PRZED korekta.
"""
from __future__ import annotations

from datetime import date

import pytest

from data_layer.db.connection import connect
from data_layer.sec.facts_repo import FactsRepository, PITMode
from data_layer.sec.xbrl_parser import Fact, parse_company_facts

CIK = 999999


def _fact(value: float, filed: date, accession: str, form: str = "10-K") -> Fact:
    return Fact(
        cik=CIK,
        taxonomy="us-gaap",
        tag="Revenues",
        unit="USD",
        value=value,
        period_start=date(2019, 1, 1),
        period_end=date(2019, 12, 31),
        fy=2019,
        fp="FY",
        form=form,
        filed_date=filed,
        accession=accession,
        frame="CY2019",
    )


ORIGINAL = _fact(1_000_000.0, date(2020, 2, 15), "0000999999-20-000001")
RESTATED = _fact(900_000.0, date(2021, 3, 1), "0000999999-21-000009", form="10-K/A")


@pytest.fixture()
def repo():
    con = connect(":memory:")
    r = FactsRepository(con)
    r.upsert_facts([ORIGINAL, RESTATED])
    yield r
    con.close()


def test_fact_invisible_before_it_was_filed(repo):
    """Rdzen ochrony przed look-ahead: 1 stycznia 2020 nikt nie znal
    wyniku za FY2019, bo raport zlozono dopiero 15 lutego."""
    assert repo.get_facts_as_of(CIK, date(2020, 1, 1), ["Revenues"]) == []


def test_original_value_before_restatement(repo):
    got = repo.get_facts_as_of(CIK, date(2020, 6, 1), ["Revenues"])
    assert len(got) == 1
    assert got[0].value == 1_000_000.0
    assert got[0].accession == ORIGINAL.accession


def test_restated_value_after_restatement(repo):
    got = repo.get_facts_as_of(CIK, date(2021, 6, 1), ["Revenues"])
    assert len(got) == 1, "Deduplikacja zawiodla - dwie wersje tego samego okresu"
    assert got[0].value == 900_000.0
    assert got[0].form == "10-K/A"


def test_as_originally_reported_mode(repo):
    got = repo.get_facts_as_of(
        CIK, date(2021, 6, 1), ["Revenues"], mode=PITMode.AS_ORIGINALLY_REPORTED
    )
    assert got[0].value == 1_000_000.0


def test_restatement_history_is_chronological(repo):
    hist = repo.restatement_history(CIK, "Revenues", date(2019, 12, 31))
    assert [h.value for h in hist] == [1_000_000.0, 900_000.0]


def test_reporting_lag(repo):
    got = repo.get_facts_as_of(CIK, date(2020, 6, 1), ["Revenues"])[0]
    assert got.lag_days == 46, "Opoznienie raportowania liczone zle"


def test_missing_as_of_date_is_rejected(repo):
    """Brak daty odciecia musi byc bledem, nie cichym domyslem."""
    with pytest.raises(ValueError):
        repo.get_facts_as_of(CIK, None, ["Revenues"])  # type: ignore[arg-type]


def test_append_only_never_overwrites(repo):
    """Ponowny ingest tego samego pliku nie moze zmienic historii."""
    repo.upsert_facts([ORIGINAL, RESTATED])
    assert len(repo.restatement_history(CIK, "Revenues", date(2019, 12, 31))) == 2


def test_parser_skips_facts_without_filed_date():
    """Fakt bez daty zlozenia jest bezuzyteczny w systemie PIT.
    Odrzucamy go zamiast zgadywac date."""
    payload = {
        "cik": CIK,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2019-01-01", "end": "2019-12-31", "val": 1,
                             "accn": "x", "filed": "2020-02-15"},
                            {"start": "2019-01-01", "end": "2019-12-31", "val": 2,
                             "accn": "y"},  # brak filed
                        ]
                    }
                }
            }
        },
    }
    facts = list(parse_company_facts(payload, tags={"Revenues"}))
    assert len(facts) == 1
    assert facts[0].value == 1


# ---------------------------------------------------------------------
# Test integracyjny: wymaga sieci i SEC_USER_AGENT.
#   pytest -m integration
# ---------------------------------------------------------------------
@pytest.mark.integration
def test_real_apple_revenue_as_of_2020():
    """Realna bramka z harmonogramu T1-T2.

    Weryfikacja reczna: wejdz na EDGAR, znajdz 10-K Apple za FY2019
    (zlozony 2019-10-31) i porownaj przychod z wartoscia zwrocona tutaj.
    Test sprawdza mechanike; zgodnosc liczby z filingiem sprawdzasz OKIEM.
    """
    from data_layer.sec.edgar_client import EdgarClient

    client = EdgarClient()
    cik = client.resolve_cik("AAPL")
    con = connect(":memory:")
    repo = FactsRepository(con)
    repo.upsert_facts(parse_company_facts(client.company_facts(cik)))

    series = repo.get_metric_series(cik, date(2020, 6, 1), "revenue")
    assert series, "Brak danych o przychodach - sprawdz mapowanie tagow"

    for fv in series:
        assert fv.filed_date <= date(2020, 6, 1), "LOOK-AHEAD: fakt z przyszlosci"

    fy2019 = [s for s in series if s.period_end == date(2019, 9, 28)]
    assert fy2019, "Brak FY2019 - sprawdz rok podatkowy spolki"
    print(f"\nAAPL FY2019 przychod wg wiedzy na 2020-06-01: {fy2019[0].value:,.0f} "
          f"(zlozony {fy2019[0].filed_date}, {fy2019[0].form})")
