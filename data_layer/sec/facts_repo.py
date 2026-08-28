"""Repozytorium faktow SEC.

TO JEST JEDYNA LINIA OBRONY PRZED LOOK-AHEAD BIAS.

Kazda metoda odczytu WYMAGA as_of_date jako argumentu pozycyjnego.
Nie ma wartosci domyslnej i nie ma metody "daj mi wszystko". To celowe:
jesli filtrowanie po dacie jest opcjonalne, predzej czy pozniej ktos
(Ty za trzy miesiace) je pominie i backtest po cichu zacznie klamac.

Dwa tryby rekonstrukcji, oba poprawne, ale odpowiadajace na inne pytania:

  LATEST_KNOWN (domyslny)
      Ostatnia wersja zlozona przed as_of_date. Odpowiada na pytanie
      "co wiedzial rynek tego dnia". Wlasciwy tryb do backtestu sygnalow.

  AS_ORIGINALLY_REPORTED
      Pierwsza wersja, jaka kiedykolwiek zlozono dla danego okresu.
      Odpowiada na pytanie "co spolka raportowala pierwotnie".
      Uzyteczny do badania jakosci raportowania i skali restatementow.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable, Sequence

import duckdb

from .xbrl_parser import CORE_TAGS, Fact

log = logging.getLogger(__name__)


class PITMode(str, Enum):
    LATEST_KNOWN = "latest_known"
    AS_ORIGINALLY_REPORTED = "as_originally_reported"


@dataclass(frozen=True, slots=True)
class FactValue:
    tag: str
    value: float | None
    unit: str
    period_start: date | None
    period_end: date
    form: str | None
    fp: str | None
    filed_date: date
    accession: str

    @property
    def lag_days(self) -> int:
        """Ile dni po zamknieciu okresu dana stala sie publiczna."""
        return (self.filed_date - self.period_end).days


class FactsRepository:
    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con

    # -- zapis --------------------------------------------------------
    def upsert_facts(self, facts: Iterable[Fact]) -> int:
        """Zapis append-only. Konflikt na kluczu = ten sam fakt z tego
        samego zlozenia, wiec pomijamy. Nigdy nie nadpisujemy wartosci."""
        rows = [
            (
                f.cik, f.taxonomy, f.tag, f.unit, f.value,
                f.period_start, f.period_end, f.fy, f.fp, f.form,
                f.filed_date, f.accession, f.frame,
            )
            for f in facts
        ]
        if not rows:
            return 0
        self.con.execute("BEGIN")
        try:
            self.con.executemany(
                """
                INSERT INTO sec_facts
                    (cik, taxonomy, tag, unit, value, period_start, period_end,
                     fy, fp, form, filed_date, accession, frame)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        return len(rows)

    # -- odczyt PIT ---------------------------------------------------
    def get_facts_as_of(
        self,
        cik: int,
        as_of_date: date,
        tags: Sequence[str],
        mode: PITMode = PITMode.LATEST_KNOWN,
        min_period_end: date | None = None,
    ) -> list[FactValue]:
        """Zwraca stan wiedzy o spolce na dany dzien.

        Deduplikacja po (tag, unit, period_start, period_end): dla kazdego
        okresu jedna wartosc, wybrana zgodnie z trybem.
        """
        if as_of_date is None:
            raise ValueError("as_of_date jest obowiazkowe. Brak daty = look-ahead bias.")
        if not tags:
            raise ValueError("Podaj przynajmniej jeden tag.")

        # LATEST_KNOWN: najpozniejsze zlozenie <= as_of.
        # AS_ORIGINALLY_REPORTED: najwczesniejsze zlozenie w ogole,
        #   ale nadal odciete przez as_of - inaczej pierwotny raport
        #   zlozony PO as_of przeciekalby do przeszlosci.
        order = "filed_date DESC, accession DESC" if mode is PITMode.LATEST_KNOWN \
            else "filed_date ASC, accession ASC"

        placeholders = ",".join("?" for _ in tags)
        params: list[object] = [cik, as_of_date, *tags]
        period_clause = ""
        if min_period_end is not None:
            period_clause = "AND period_end >= ?"
            params.append(min_period_end)

        sql = f"""
            WITH filtered AS (
                SELECT *
                FROM sec_facts
                WHERE cik = ?
                  AND filed_date <= ?
                  AND tag IN ({placeholders})
                  {period_clause}
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY tag, unit, period_start, period_end
                    ORDER BY {order}
                ) AS rn
                FROM filtered
            )
            SELECT tag, value, unit, period_start, period_end,
                   form, fp, filed_date, accession
            FROM ranked
            WHERE rn = 1
            ORDER BY period_end DESC, tag
        """
        return [FactValue(*row) for row in self.con.execute(sql, params).fetchall()]

    def get_metric_series(
        self,
        cik: int,
        as_of_date: date,
        concept: str,
        mode: PITMode = PITMode.LATEST_KNOWN,
    ) -> list[FactValue]:
        """Szereg czasowy dla pojecia z CORE_TAGS, z rozwiazaniem
        alternatywnych tagow.

        Spolki zmieniaja tagi miedzy latami (klasyczny przypadek:
        'Revenues' -> 'RevenueFromContractWithCustomerExcludingAssessedTax'
        po ASC 606). Bierzemy pierwszy tag z listy priorytetow, ktory
        w ogole ma dane - ale RAPORTUJEMY, ktory to byl, bo mieszanie
        definicji w jednym szeregu to cichy blad.
        """
        if concept not in CORE_TAGS:
            raise KeyError(f"Nieznane pojecie {concept!r}. Dostepne: {sorted(CORE_TAGS)}")
        for tag in CORE_TAGS[concept]:
            values = self.get_facts_as_of(cik, as_of_date, [tag], mode=mode)
            if values:
                return values
        return []

    # -- diagnostyka --------------------------------------------------
    def restatement_history(self, cik: int, tag: str, period_end: date) -> list[FactValue]:
        """Wszystkie zlozone wersje jednej wartosci, chronologicznie.

        Bez odciecia as_of - to narzedzie diagnostyczne, nie badawcze.
        Nie uzywaj w kodzie strategii.
        """
        sql = """
            SELECT tag, value, unit, period_start, period_end,
                   form, fp, filed_date, accession
            FROM sec_facts
            WHERE cik = ? AND tag = ? AND period_end = ?
            ORDER BY filed_date ASC
        """
        return [FactValue(*r) for r in self.con.execute(sql, [cik, tag, period_end]).fetchall()]

    def coverage_report(self, cik: int, as_of_date: date) -> dict[str, str]:
        """Ktore pojecia core sa dostepne na dany dzien.

        Realizuje regule #13 briefu: system ma powiedziec
        INSUFFICIENT DATA zamiast wymyslac brakujace wartosci.
        """
        out: dict[str, str] = {}
        for concept in CORE_TAGS:
            series = self.get_metric_series(cik, as_of_date, concept)
            if not series:
                out[concept] = "MISSING"
            elif len(series) < 4:
                out[concept] = f"PARTIAL ({len(series)} okresow)"
            else:
                out[concept] = f"OK ({len(series)} okresow, ostatni {series[0].period_end})"
        return out
