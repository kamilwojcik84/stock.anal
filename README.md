# Stock Analyzer — Faza 0: Data Foundation

Uniwersum: US equities, mcap > $2B, bez financials i REIT-ów.
Horyzont: fundamentalny. Bez CFD, bez dźwigni, do bramki z Fazy 2.

## Uruchomienie

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # wpisz SEC_USER_AGENT (email obowiązkowy)

pytest                        # 9 testów jednostkowych, bez sieci
pytest -m integration         # test na realnych danych AAPL

python scripts/bootstrap.py AAPL MSFT NVDA --report --as-of 2020-06-01
```

EODHD nie jest potrzebne do startu. `--prices` włączysz w tygodniu 3.

## Co tu jest i dlaczego

| Moduł | Rola |
|---|---|
| `data_layer/sec/edgar_client.py` | SEC EDGAR z limiterem 6 req/s i cache na dysku |
| `data_layer/sec/xbrl_parser.py` | companyfacts → płaskie fakty; ~22 pojęcia core |
| `data_layer/sec/facts_repo.py` | **rekonstrukcja PIT** — jedyna linia obrony przed look-ahead |
| `data_layer/prices/eodhd_client.py` | ceny EOD + uniwersum ze spółkami zdelistowanymi |
| `data_layer/db/schema.sql` | DuckDB, `sec_facts` append-only |

### Dwie decyzje, które trzymają cały projekt

**1. `get_facts_as_of()` wymaga `as_of_date` jako argumentu pozycyjnego.**
Brak wartości domyślnej, brak metody „daj mi wszystko". Jeśli filtrowanie
po dacie jest opcjonalne, prędzej czy później je pominiesz i backtest
zacznie po cichu kłamać. Testy sprawdzają, że `None` rzuca wyjątkiem.

**2. `sec_facts` jest append-only.**
Restatement to nowy wiersz z nowym `accession`, nigdy UPDATE. Ta sama
wartość za FY2019 istnieje w bazie w tylu wersjach, ile razy ją złożono.
To nie są duplikaty — to historia wiedzy rynku.

Dwa tryby odczytu:
- `LATEST_KNOWN` — co wiedział rynek tego dnia (domyślny, do backtestu)
- `AS_ORIGINALLY_REPORTED` — co spółka raportowała pierwotnie (do badania jakości raportowania)

## Bramka Fazy 0 — kryteria zaliczenia

- [x] `pytest` zielony (9/9): fakt niewidoczny przed złożeniem, restatement obsłużony, brak daty odrzucony, ponowny ingest nie zmienia historii
- [ ] `pytest -m integration` przechodzi na realnym AAPL
- [ ] **Ręczna weryfikacja:** otwierasz 10-K Apple za FY2019 w EDGAR i porównujesz przychód okiem z wartością z `--report`. Test sprawdza mechanikę, nie poprawność liczby.
- [ ] `--report` na 5 spółkach z różnych sektorów, świadoma ocena które pojęcia mają `MISSING`

Ostatni punkt jest ważniejszy niż wygląda. `MISSING` przy `capex` dla spółki
software'owej to norma. `MISSING` przy `revenue` to błąd mapowania tagów,
który zatruje wszystko dalej.

## Znane luki (świadome, nie przeoczenia)

1. **Q4 nie jest wyliczany.** 10-K zawiera FY, 10-Q zawiera Q1–Q3. Q4 = FY − (Q1+Q2+Q3). Zadanie na T3–T4.
2. **Zmiany tagów między latami.** `get_metric_series` bierze pierwszy tag z listy priorytetów, który ma dane. Przy przejściu ASC 606 może to oznaczać zmianę definicji w środku szeregu. Do wykrycia na golden set.
3. **Brak IFRS.** Spółki zagraniczne (20-F) mają inne tagi. Poza uniwersum v1.
4. **Uniwersum PIT nieukończone.** `universe/` jest puste — mapowanie ticker↔CIK dla spółek zdelistowanych wymaga EODHD, tydzień 3.
5. **Brak sektorów.** Kolumna `sector` pusta; routing z SIC to T5–T6.

## Kolejny krok

T3–T4: golden dataset. 20 spółek z 6 sektorów, wszystkie metryki policzone
**ręcznie z filingów**, z linkiem do źródła w komentarzu testu. Dopiero
przeciwko nim piszemy silnik metryk.

Kolejność jest nieprzypadkowa: kod napisany szybko wygląda poprawnie.
Golden set jest jedynym sposobem, żeby się dowiedzieć, że nie jest.
