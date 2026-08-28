-- =====================================================================
-- PHASE 0 SCHEMA  (DuckDB)
--
-- DWIE ZASADY NIENARUSZALNE:
--   1. sec_facts jest APPEND-ONLY. Restatement = nowy wiersz z nowym
--      accession. Nigdy UPDATE, nigdy DELETE. Utrata tej własności
--      oznacza utratę możliwości odtworzenia przeszłości.
--   2. Każde zapytanie badawcze filtruje po filed_date <= as_of_date.
--      Egzekwowane w warstwie repozytorium (facts_repo.py), nie w
--      kodzie strategii.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Securities master. Zawiera RÓWNIEŻ spółki zdelistowane — bez tego
-- każdy backtest ma survivorship bias.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS securities (
    cik             BIGINT      NOT NULL,
    ticker          VARCHAR     NOT NULL,
    name            VARCHAR,
    exchange        VARCHAR,
    sic             VARCHAR,
    sector          VARCHAR,          -- routing sektorowy (reguła #28)
    first_seen      DATE,
    delisted_date   DATE,             -- NULL = aktywna
    is_active       BOOLEAN DEFAULT TRUE,
    source          VARCHAR,
    ingested_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (cik, ticker)
);

-- ---------------------------------------------------------------------
-- Surowe fakty XBRL z SEC companyfacts.
--
-- filed_date to najważniejsza kolumna w całej bazie. To ona odróżnia
-- "co się wydarzyło" od "co było wiadome".
--
-- period_start NULL  => fakt punktowy (instant): bilans, shares outstanding
-- period_start NOT NULL => fakt okresowy (duration): przychód, FCF
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sec_facts (
    cik             BIGINT      NOT NULL,
    taxonomy        VARCHAR     NOT NULL,   -- 'us-gaap', 'dei', 'ifrs-full'
    tag             VARCHAR     NOT NULL,   -- 'Revenues', 'Assets', ...
    unit            VARCHAR     NOT NULL,   -- 'USD', 'shares', 'USD/shares'
    value           DOUBLE,
    period_start    DATE,
    period_end      DATE        NOT NULL,
    fy              INTEGER,
    fp              VARCHAR,                -- 'FY','Q1','Q2','Q3'
    form            VARCHAR,                -- '10-K','10-Q','8-K','20-F'
    filed_date      DATE        NOT NULL,
    accession       VARCHAR     NOT NULL,
    frame           VARCHAR,
    ingested_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (cik, taxonomy, tag, unit, period_end, accession)
);

CREATE INDEX IF NOT EXISTS ix_facts_pit   ON sec_facts (cik, tag, filed_date);
CREATE INDEX IF NOT EXISTS ix_facts_end   ON sec_facts (cik, period_end);

-- ---------------------------------------------------------------------
-- Ceny EOD. adj_close liczony przez dostawcę; trzymamy też raw close,
-- bo współczynniki korekty bywają rewidowane wstecz.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_daily (
    ticker          VARCHAR     NOT NULL,
    date            DATE        NOT NULL,
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    adj_close       DOUBLE,
    volume          BIGINT,
    source          VARCHAR,
    ingested_at     TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (ticker, date)
);

-- ---------------------------------------------------------------------
-- Metryki policzone. inputs_json + source_accessions dają traceability
-- wymagany regułą #14 briefu: każda liczba prowadzi do źródła.
--
-- as_of_date = data, na którą metryka była policzalna z dostępnej wiedzy.
-- Nie mylić z period_end.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metrics (
    cik                 BIGINT      NOT NULL,
    as_of_date          DATE        NOT NULL,
    name                VARCHAR     NOT NULL,
    value               DOUBLE,
    unit                VARCHAR,
    quality_flag        VARCHAR,        -- 'OK','PARTIAL','INSUFFICIENT_DATA'
    inputs_json         VARCHAR     NOT NULL,   -- traceability §3.3: bez wyjątków
    source_accessions   VARCHAR     NOT NULL,   -- lista, przecinkami
    code_sha            VARCHAR     NOT NULL,
    computed_at         TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (cik, as_of_date, name)
);

-- ---------------------------------------------------------------------
-- Sygnały. model_version + code_sha są obowiązkowe: bez nich po trzech
-- miesiącach nie odtworzysz, jaka wersja logiki to wygenerowała.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id              VARCHAR     PRIMARY KEY,
    as_of_date      DATE        NOT NULL,
    ticker          VARCHAR     NOT NULL,
    cik             BIGINT,
    kind            VARCHAR     NOT NULL,
    payload_json    VARCHAR     NOT NULL,
    model_version   VARCHAR     NOT NULL,
    code_sha        VARCHAR     NOT NULL,
    created_at      TIMESTAMP DEFAULT current_timestamp
);

-- ---------------------------------------------------------------------
-- Wyniki. realized_costs osobno — backtest bez modelu kosztów kłamie.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outcomes (
    signal_id           VARCHAR     NOT NULL,
    horizon_days        INTEGER     NOT NULL,
    fwd_return          DOUBLE,
    benchmark_return    DOUBLE,
    realized_costs      DOUBLE,
    evaluated_at        TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (signal_id, horizon_days)
);

-- ---------------------------------------------------------------------
-- Log ingestów. Obserwowalność (reguła #26): kiedy co pobraliśmy,
-- co się nie udało, które dane są stale.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_log (
    id              VARCHAR     PRIMARY KEY,
    source          VARCHAR     NOT NULL,
    entity          VARCHAR,
    status          VARCHAR     NOT NULL,   -- 'OK','FAILED','EMPTY','CACHED'
    rows_written    BIGINT,
    message         VARCHAR,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP DEFAULT current_timestamp
);
