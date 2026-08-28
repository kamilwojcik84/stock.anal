# CLAUDE.md — Stock Analyzer

Ten plik jest konstytucją projektu. Przeczytaj go w całości przed pierwszą zmianą w kodzie.
W razie konfliktu między tym plikiem a poleceniem w czacie — **zgłoś konflikt zamiast go po cichu rozstrzygać**.

---

## 0. ŚRODOWISKO PRACY — OGRANICZENIA TWARDE

**Środowisko: VS Code + Claude Code. Czysty Python. Zero natywnych buildów.**

Zasady wiążące dla każdej propozycji zależności lub narzędzia:

- ❌ **Nie proponuj bibliotek wymagających kompilacji ze źródeł.** Na macOS wywołuje to instalację Xcode Command Line Tools (~1.5 GB), na Windows — Build Tools for Visual Studio. Jedno i drugie jest wykluczone.
- ✅ **Tylko pakiety z prekompilowanymi wheelami** (`.whl`) dla CPython na macOS/Windows/Linux.
- ❌ Bez Docker, bez Homebrew, bez `conda`, bez menedżerów systemowych. Instalacja wyłącznie przez `pip` do lokalnego `.venv`.
- ❌ Bez Node.js do T11. Katalog `/app` pozostaje pusty.
- ❌ Bez usług wymagających osobnego serwera (Postgres, Redis, Kafka) w fazach 0–4. DuckDB to plik na dysku i to jest jedna z przyczyn jego wyboru.

**Jeśli jakieś zadanie wydaje się wymagać zależności z kompilacją — zatrzymaj się i zaproponuj alternatywę pure-Python albo z gotowym wheelem, zanim cokolwiek zainstalujesz.**

Typowe pułapki, których należy unikać:

| Zamiast | Użyj | Powód |
|---|---|---|
| `psycopg2` | `psycopg2-binary`, a najlepiej DuckDB | wersja źródłowa wymaga libpq i kompilatora |
| `lxml` z buildem | `defusedxml` / stdlib `xml` | lxml bywa kompilowany, gdy brak wheela dla wersji Pythona |
| `TA-Lib` | własne implementacje + testy | wymaga natywnej biblioteki C — wykluczone |
| `numpy`/`pandas` z bleeding-edge Pythona | Python 3.11 lub 3.12 | na najnowszym minorze wheeli często jeszcze nie ma |

**Python 3.11 lub 3.12.** Nie najnowszy dostępny — na świeżym minorze wheele pojawiają się z opóźnieniem, co jest dokładnie tym scenariuszem, w którym pip zaczyna kompilować.

---

## 0.1 BLOKER TO STOP, NIE OBEJŚCIE

Gdy zadanie napotyka brakujący warunek środowiskowy — brak klucza API, brak `.env`,
brak zależności, niespójna konfiguracja providera lub modelu — jest to **STOP i pytanie
do właściciela projektu**, nie przeszkoda do cichego obejścia.

Zakazy twarde:

- ❌ **Nie zmieniaj konfiguracji projektu, żeby ominąć bloker.** Dotyczy
  `.taskmaster/config.json`, modeli, providerów, zmiennych środowiskowych i wszystkiego,
  co da się przestawić zamiast rozwiązać.
- ❌ Nie uruchamiaj `task-master models --set-*` bez mojej wyraźnej zgody w tej samej
  wymianie zdań.
- ❌ Nie podstawiaj innego modelu ani providera „żeby zadziałało".
- ❌ Nie generuj PRD, zadań ani innych artefaktów po fallbacku na inny model bez
  poinformowania mnie PRZED wykonaniem pracy.
- ❌ Nie twórz ani nie modyfikuj `.env`. Zgłoś, czego brakuje — wpiszę sam.

Nakazy:

- ✅ Zatrzymaj się, opisz bloker i opcje, poczekaj na decyzję.
- ✅ **Przed KAŻDYM wywołaniem AI przez Task Mastera** (`parse-prd`, `expand`,
  `analyze-complexity`, `update-task`) wypisz w odpowiedzi, jaki model i provider
  zostaną użyte. Jeśli to nie jest ustalona konfiguracja — zatrzymaj się i zapytaj.
- ✅ Jeśli placeholder w moim poleceniu nie został wypełniony treścią — zgłoś to
  i zatrzymaj się. Nie wymyślaj brakującej treści.

Zmiana konfiguracji w celu ominięcia blokera jest naruszeniem tej konstytucji, nawet
jeśli „działa". Reguła jest szersza niż Task Master: obejście konfiguracją to decyzja
architektoniczna w przebraniu problemu technicznego.

---

## 1. CEL I METRYKA SUKCESU

Budujemy narzędzie do analizy fundamentalnej spółek US, w którym **każda liczba jest odtwarzalna dla dowolnej daty historycznej bez look-ahead bias**.

Metryka sukcesu po 12 tygodniach — celowo **nie jest kwotą**:

> Mam silnik, który dla dowolnej historycznej daty odtwarza stan wiedzy rynkowej bez look-ahead, i mam policzoną expectancy netto (po kosztach) dla co najmniej jednej hipotezy sygnałowej, out-of-sample.

Zysk jest konsekwencją tego, nie alternatywą. Jeśli w kodzie lub w rozmowie pojawi się presja na skrócenie weryfikacji „bo widać, że działa" — to jest moment, w którym projekt przestaje być systemem analitycznym. Twoim zadaniem jest to nazwać.

---

## 2. USTALENIA — DECYZJE ZAMKNIĘTE

Te decyzje zapadły po krytycznym review i **nie podlegają cichej zmianie**. Możesz je zakwestionować argumentem, ale nie możesz ich obejść implementacją.

| # | Decyzja | Powód |
|---|---|---|
| 1 | **Bez CFD.** Akcje kasowe, bez dźwigni, do bramki z Fazy 2 | backtest na OHLCV bazowego ≠ handel syntetykiem ze swapem i innym spreadem; rozjazd danych unieważnia całą dyscyplinę PIT |
| 2 | **Bez composite score 0–100.** Wektor 5 wymiarów, percentyle sektorowe | wagi typu 15/15/15/10 nie mają uzasadnienia; agregacja niszczy informację (91 = świetna firma droga czy przeciętna tania?) |
| 3 | **Uniwersum: US, mcap > $2B, bez financials i REIT-ów** | SEC XBRL daje darmowy PIT; GPW nie ma odpowiednika i nie da się tam wykonać wiarygodnego backtestu (za mało niezależnych obserwacji). Banki i REIT-y mają inną ekonomikę — ROIC/FCF/EV-EBITDA nie mają dla nich sensu |
| 4 | **IBKR, na razie tylko paper account** | egzekucja agencyjna, API, darmowe paper trading; potrzebne w Fazie 4 |
| 5 | **EODHD darmowy tier teraz, płatny (~$20/mies.) od T3** | nie płacimy za dane, których jeszcze nie umiemy użyć |
| 6 | **12 tygodni × 20h.** Przyspieszenie dozwolone w T1–T2 i T11–T12, **zakazane w T3–T4** | golden dataset musi powstać niezależnie od kodu, inaczej traci sens |
| 7 | **Reverse DCF zamiast forward DCF** | forward DCF automatyczny to generator liczb — fair value jest funkcją terminal growth i WACC, które i tak zgadujemy. Reverse DCF daje wynik falsyfikowalny |
| 8 | **Moat, TAM, market share poza scoringiem** | brak danych; wypełnione przez LLM byłyby 20% halucynacji z ładnym uzasadnieniem i zerową powtarzalnością |
| 9 | **LLM = falsyfikator, nie narrator** | model zawsze napisze przekonującą narrację dla szumu, co zwiększa pewność siebie bez zwiększania przewagi |

### Budżet danych
- **Teraz:** SEC EDGAR ($0) + FRED ($0) + EODHD free tier. Cel ≤ $50/mies.
- **Od T3:** EODHD EOD All World (~$20/mies.)
- **Po bramce z Fazy 2, do $200/mies.:** Sharadar SF1+SEP — **nie jako zamiennik SEC, tylko jako niezależna kontrola naszego parsera.** Rozjazd naszego ROIC z ich ROIC = mamy błąd.

---

## 3. ZASADY NIENARUSZALNE

### 3.1 Point-in-time
- Każde zapytanie badawcze filtruje po `filed_date <= as_of_date`.
- Egzekwowane w warstwie repozytorium (`facts_repo.py`), **nigdy w kodzie strategii**.
- `as_of_date` jest argumentem pozycyjnym bez wartości domyślnej. Nie dodawaj domyślnej. Nie dodawaj metody „daj mi wszystko".
- Jeśli tworzysz nowy dostęp do danych historycznych — musi mieć ten sam kontrakt.

### 3.2 Append-only
- `sec_facts` nigdy nie dostaje UPDATE ani DELETE.
- Restatement = nowy wiersz z nowym `accession`.
- Wiele wersji tej samej wartości to **nie duplikaty**. To historia wiedzy rynku.

### 3.3 Traceability
- Każda policzona metryka zapisuje `inputs_json` + `source_accessions` + `code_sha`.
- Każdy sygnał zapisuje `model_version` + `code_sha`.
- Bez tego po trzech miesiącach nie odtworzysz, jaka logika wygenerowała wynik.

### 3.4 Brak fałszywej precyzji
- Braki danych → `INSUFFICIENT_DATA`, nigdy imputacja, nigdy wartość domyślna.
- Nie zwracaj liczby z dokładnością większą niż uzasadniona metodą.
- `quality_flag` na każdej metryce: `OK` / `PARTIAL` / `INSUFFICIENT_DATA`.

### 3.5 Determinizm
- Cały scoring deterministyczny i testowalny. Ten sam input = ten sam output, zawsze.
- LLM nie dotyka liczb. Nigdy.

---

## 4. ARCHITEKTURA

```
SEC EDGAR (PIT, $0) ──┐
EODHD (ceny + delisted)├─→ DATA LAYER ─→ METRICS ─→ FACTORS ─→ RESEARCH/BACKTEST
FRED (makro, $0)     ──┘      │                                        │
                              └──────── traceability ──────────────────┘
                                                                        ↓
                                                        LLM (falsyfikacja) → RAPORT
```

### Model danych
```
securities        (cik, ticker, sector, delisted_date, is_active)   -- Z DELISTED
sec_facts         (cik, tag, value, period_end, filed_date, accession)  -- APPEND-ONLY
price_daily       (ticker, date, ohlcv, adj_close)
metrics           (cik, as_of_date, name, value, quality_flag, inputs_json, source_accessions)
factor_scores     (cik, as_of_date, factor, raw_value, sector_percentile)
signals           (id, as_of_date, ticker, payload_json, model_version, code_sha)
outcomes          (signal_id, horizon_days, fwd_return, benchmark_return, realized_costs)
ingest_log        (source, entity, status, rows_written, message)
```

Kluczowe: **dwie daty na wszystkim** — czego dotyczy (`period_end`) i kiedy stało się znane (`filed_date`).

### Stack
- **DuckDB + Parquet** w warstwie badawczej — kolumnowa, zero ops, skan 1500 spółek × 25 lat w sekundach
- **Postgres dopiero w Fazie 5**, pod stan aplikacji
- **FastAPI** — Faza 5
- **Next.js + Tailwind** — Faza 6, katalog `/app` ma zostać **pusty do T11**
- Python 3.11+, pytest

---

## 5. STAN OBECNY — FAZA 0 UKOŃCZONA

Zbudowane i przetestowane (9/9 zielonych bez sieci):

| Moduł | Rola |
|---|---|
| `data_layer/sec/edgar_client.py` | SEC EDGAR, limiter 6 req/s, cache gzip na dysku |
| `data_layer/sec/xbrl_parser.py` | companyfacts → płaskie fakty, ~22 pojęcia core |
| `data_layer/sec/facts_repo.py` | **rekonstrukcja PIT, dwa tryby** — rdzeń projektu |
| `data_layer/prices/eodhd_client.py` | ceny EOD + uniwersum ze zdelistowanymi |
| `data_layer/db/schema.sql` | DuckDB, append-only |
| `tests/test_pit_reconstruction.py` | bramka: restatement, look-ahead, append-only |
| `scripts/bootstrap.py` | ingest end-to-end + raport pokrycia |

Tryby odczytu PIT:
- `LATEST_KNOWN` — co wiedział rynek tego dnia (domyślny, do backtestu)
- `AS_ORIGINALLY_REPORTED` — co spółka raportowała pierwotnie (do badania jakości raportowania)

### Znane luki — świadome, nie przeoczenia
1. **Q4 nie jest wyliczany.** 10-K = FY, 10-Q = Q1–Q3. Q4 = FY − (Q1+Q2+Q3). Zadanie T3–T4.
2. **Zmiany tagów między latami** (np. ASC 606: `Revenues` → `RevenueFromContractWithCustomer...`). `get_metric_series` bierze pierwszy tag z listy priorytetów — grozi zmianą definicji w środku szeregu. Do wykrycia na golden set.
3. **Brak IFRS** (20-F). Poza uniwersum v1.
4. **`universe/` puste** — mapowanie ticker↔CIK dla zdelistowanych wymaga EODHD, T3.
5. **Brak sektorów** — routing z SIC to T5–T6.
6. **Ceny bez PIT.** `price_daily` nie ma `filed_date` ani vintage; `adj_close` jest korygowany wstecz o przyszłe splity i dywidendy → look-ahead dla każdej cechy opartej na poziomie ceny. Brak `get_prices_as_of` i tabeli splitów/dywidend. Cała dyscyplina PIT egzekwowana tylko na `sec_facts`, nie na cenach. **Do rozstrzygnięcia przed T7.**
7. **Join ticker↔CIK niedatowany.** Fakty są kluczowane po CIK (stabilne), ceny po tickerze (niestabilne); most to aktualna, aktywna mapa SEC (`resolve_cik`). Zmiana lub recykling tickera → join w złą spółkę. Brak `valid_from/valid_to` na relacji. **Do rozstrzygnięcia przed T7.**
8. **Brak PIT membership uniwersum.** Nie modelujemy, kto należał do uniwersum (>$2B, non-financial, non-REIT) na dzień X; percentyle liczone wobec dzisiejszego składu = survivorship + look-ahead. **Do rozstrzygnięcia przed T7.**
9. **Infrastruktura — Task Master: `max_tokens: 64000` non-streaming → ECONNRESET.** `parse-prd`/`expand` wysyłają żądania z `max_tokens: 64000`, ignorując `maxTokens: 32000` z `.taskmaster/config.json`. Duże żądanie non-streaming trzyma połączenie otwarte przez całą generację bez ani jednego bajtu w drugą stronę (profil `%CPU 0,0`, stan `S`), a proxy/NAT zamyka bezczynne połączenie → `ECONNRESET`. To **powtarzalna właściwość tego łącza**, nie chwilowy blip (potwierdzone 44-min zawisem i wielokrotnym `other side closed`). Dlatego `expand` uruchamiać **po jednym zadaniu**, nie `--all`. **Przy nawrotach rozważyć streaming albo mniejsze żądania — decyzja właściciela, nie Claude Code.**

---

## 6. ROADMAPA — 12 TYGODNI × 20h

### T1–T2 — Data Foundation ✅ scaffolding gotowy
**Bramka:** zapytanie „stan wiedzy o AAPL na 2020-06-01" zwraca dokładnie to, co było wtedy złożone — **zweryfikowane ręcznie w EDGAR, okiem, przeciwko 10-K**.

### T3–T4 — Golden dataset + metryki core
20 spółek z 6 sektorów, wszystkie metryki policzone **ręcznie z filingów**, z linkiem do źródła w komentarzu testu. Dopiero przeciwko nim piszemy silnik.
Metryki: revenue growth, marże, FCF, net debt, coverage.
Edge case'y obowiązkowo: ujemny FCF, zerowy przychód, IPO z krótką historią, spin-off, zmiana roku podatkowego.
**Bramka:** 100% zgodności z golden set.
**Nie przyspieszaj tego etapu.** Golden set ma sens tylko wtedy, gdy powstaje niezależnie od kodu.

### T5–T6 — ROIC, sector routing, percentyle
ROIC dostaje własny tydzień: invested capital z leasingami operacyjnymi (ASC 842), goodwill in/out, excess cash, NOPAT z efektywną stopą. To nie jest „jedna z dziesięciu pozycji".
**Bramka:** ROIC zgodny z ręcznym wyliczeniem na 20 spółkach.

### T7–T8 — Reverse DCF + warstwa jakościowa
Output typu: *„przy cenie $X rynek zakłada 24% CAGR przychodów przez 10 lat przy 48% marży operacyjnej"*. Liczba falsyfikowalna, porównywalna z historią spółki.
LLM jako falsyfikator: „co musiałoby być prawdą, żeby teza była błędna", „czy ten katalizator jest już w cenie".

### T9–T10 — BRAMKA GO/NO-GO
Jedna hipoteza sygnałowa. Walk-forward. Model kosztów. Expectancy netto out-of-sample.
Deflated Sharpe z korektą na liczbę przetestowanych wariantów — **inaczej sam proces iteracji staje się źródłem overfittingu**.

### T11–T12 — FastAPI + minimalny UI
Tylko jeśli bramka przeszła.

---

## 7. KILL CRITERIA

Zapisane zawczasu, celowo, przed zaangażowaniem emocjonalnym:

> Jeśli po Fazie 2 żadna z trzech niezależnie przetestowanych hipotez nie wykaże dodatniej expectancy netto out-of-sample po kosztach — projekt zmienia charakter: z systemu sygnałowego na narzędzie do screeningu i researchu. Nie dokładam kapitału, nie zwiększam budżetu na dane, nie przechodzę do automatyzacji.

Narzędzie do screeningu z uczciwymi PIT fundamentami i reverse DCF ma realną wartość. To jest drugi z **dwóch akceptowalnych** wyników, nie porażka.

---

## 8. CZEGO NIE ROBIĆ

- ❌ Nie dodawaj domyślnej wartości do `as_of_date`
- ❌ Nie rób UPDATE na `sec_facts`
- ❌ Nie imputuj brakujących danych — zwróć `INSUFFICIENT_DATA`
- ❌ Nie pozwól LLM-owi liczyć ani modyfikować liczb
- ❌ Nie buduj UI przed T11
- ❌ Nie dodawaj wskaźnika, bo jest popularny — tylko jeśli poprawia expectancy
- ❌ Nie licz tego samego czynnika wielokrotnie (trend 15m/1H/4H/1D to jeden czynnik w czterech rozdzielczościach, korelacja 0.7–0.9)
- ❌ Nie optymalizuj pod wynik historyczny; 95% win rate = overfitting, nie sukces
- ❌ Nie stosuj tego samego modelu do banków, REIT-ów, SaaS i biotechu
- ❌ Nie commituj `.env`, nie loguj sekretów
- ❌ Nie instaluj zależności wymagających kompilacji ze źródeł (patrz §0) — zaproponuj alternatywę i poczekaj na decyzję

---

## 9. JAK PRACOWAĆ

### Iteracyjnie
Plan → implementacja → test → weryfikacja → review → refactor → następny etap.
Nie generuj całych faz naraz. Każdy krok musi być uruchamialny.

### Kwestionuj
Jeśli polecenie zawiera błąd, nieefektywność, ryzyko overfittingu, look-ahead, data leakage lub niepotrzebną komplikację — **powiedz to**, nie wykonuj.

Format: *„Nie rekomenduję tego. Powód: X. Lepszym rozwiązaniem jest Y."* Potem konkret.

Przy dwóch sensownych opcjach: przedstaw OPTION A / OPTION B z plusami i minusami plus rekomendację. Nie wybieraj po cichu.

### Weryfikacja > kod
Przy Claude Code wąskim gardłem nie jest pisanie kodu, tylko weryfikacja. **~40% czasu na testy i ręczne sprawdzanie liczb w filingach.** Kod powstanie szybko i będzie wyglądał poprawnie — to jest właśnie ryzyko.

### Raport po każdym milestone
```
WHAT WAS BUILT
WHAT WAS TESTED
WHAT PASSED
WHAT FAILED
WHAT WE SHOULD DO NEXT
```
Plus wprost: czego potrzebujesz ode mnie (klucz API, decyzja, weryfikacja ręczna).

### Pytania kontrolne przy każdym nowym elemencie
- Czy to rzeczywiście zwiększa przewagę?
- Czy mamy dane, żeby to policzyć? Czy są wystarczająco dobre?
- Czy da się to zbacktestować bez look-ahead / survivorship / leakage?
- Czy wskaźnik nie jest redundantny wobec już istniejących?
- Czy parametr nie został dopasowany do historii?
- Co musiałoby być prawdą, żeby nasza teza była błędna?

---

## 10. URUCHOMIENIE

Sprawdź wersję Pythona — ma być **3.11 lub 3.12** (patrz §0):
```bash
python3 --version
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt
cp .env.example .env
```

**Windows (PowerShell)**
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt
copy .env.example .env
```

Flaga `--only-binary=:all:` jest istotna: wymusza użycie prekompilowanych
wheeli i **zatrzymuje instalację z czytelnym błędem**, zamiast po cichu
uruchamiać kompilator. Jeśli kiedykolwiek zobaczysz błąd tej flagi —
to jest sygnał, że zależność nie należy do tego projektu (§0), a nie
powód, żeby flagę usunąć.

Uzupełnij `.env`: `SEC_USER_AGENT` musi zawierać prawdziwy adres e-mail,
inaczej SEC zwraca 403.

**Weryfikacja:**
```bash
pytest                        # 9 testów, bez sieci
pytest -m integration         # realny AAPL, wymaga sieci
python scripts/bootstrap.py AAPL MSFT NVDA --report --as-of 2020-06-01
```

### VS Code — minimalna konfiguracja
Rozszerzenie **Python** (Microsoft). Interpreter: `Python: Select Interpreter`
→ `.venv`. Nic więcej nie jest potrzebne; Pylance i debugger działają
bez natywnych zależności.

### Jeśli macOS mimo wszystko prosi o Command Line Tools
Najczęściej wywołuje to **`git`**, nie Python. To narzędzia wiersza poleceń
(~1.5 GB), nie pełny Xcode (~15 GB):
```bash
xcode-select --install
```
Alternatywa bez tego: zainstaluj Git z git-scm.com albo używaj VS Code
Source Control, które ma własny Git.

Jeśli prośba pojawia się przy `pip install` — flaga `--only-binary=:all:`
została pominięta. Wróć do polecenia powyżej.

---

## 11. NASTĘPNY KROK

T3–T4: golden dataset. Skład ustalimy na podstawie wyniku `--report` — potrzebne jest realne pokrycie danych dla spółek z różnych sektorów, żeby wybrać 20 przypadków testowych obejmujących także trudne (ujemny FCF, IPO, spin-off, zmiana FY).

**Uwaga przy czytaniu `--report`:** `MISSING` przy `capex` dla spółki software'owej to norma. `MISSING` przy `revenue` to błąd mapowania tagów, który zatruje wszystko dalej.
