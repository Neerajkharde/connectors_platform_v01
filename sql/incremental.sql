-- =============================================================
-- Incremental sync support: watermarks, run log, change log
--
-- Safe to run repeatedly (every statement is idempotent) - the app
-- applies this file automatically at the start of each run.
-- Kept separate from schema.sql on purpose: schema.sql DROPs the data
-- tables, this file holds history that must survive a re-create.
-- Re-run it (or just start the app) after re-running schema.sql so the
-- triggers are re-attached.
-- =============================================================

-- -------------------------------------------------------------
-- 1. SYNC_STATE - one watermark per entity
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_state (
    entity           TEXT        PRIMARY KEY,   -- 'supplier', 'purchase_order'
    watermark_field  TEXT,                      -- SAP field the watermark refers to
    last_value       TIMESTAMP,                 -- highest field value loaded so far (naive UTC)
    last_run_id      UUID,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------
-- 2. RUN_LOG - what each run did
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_log (
    run_id       UUID        PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'RUNNING',  -- RUNNING / OK / QUOTA / FAILED
    mode         TEXT,                                    -- 'incremental' / 'full'
    sap_calls    INTEGER     NOT NULL DEFAULT 0,
    stats        JSONB       NOT NULL DEFAULT '{}'::jsonb, -- {"supplier": {"inserted":1,"updated":2,"unchanged":3}, ...}
    dropped      JSONB       NOT NULL DEFAULT '{}'::jsonb, -- {"<reason>": {"count": 3, "examples": [...]}}
    error        TEXT
);

-- -------------------------------------------------------------
-- 3. CHANGE_LOG - what changed in which record (UPDATEs only)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS change_log (
    id              BIGSERIAL   PRIMARY KEY,
    run_id          UUID,                       -- run that made the change (NULL = manual edit)
    table_name      TEXT        NOT NULL,
    record_key      JSONB       NOT NULL,       -- {"supplier": "1000"}
    change_type     TEXT        NOT NULL,       -- 'UPDATE'
    changed_fields  JSONB       NOT NULL,       -- {"supplier_name": {"old": "ABC Ltd", "new": "ABC Limited"}}
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_change_log_run     ON change_log (run_id);
CREATE INDEX IF NOT EXISTS ix_change_log_table   ON change_log (table_name, changed_at);
CREATE INDEX IF NOT EXISTS ix_change_log_key     ON change_log USING gin (record_key);

-- -------------------------------------------------------------
-- 4. Generic trigger function
--    TG_ARGV = the key column(s) of the table being logged.
--    The run id is read from the session setting app.run_id.
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION log_changes() RETURNS trigger AS $$
DECLARE
    diff jsonb;
BEGIN
    SELECT jsonb_object_agg(n.key, jsonb_build_object('old', o.value, 'new', n.value))
      INTO diff
      FROM jsonb_each(to_jsonb(NEW)) AS n
      JOIN jsonb_each(to_jsonb(OLD)) AS o ON o.key = n.key
     WHERE n.value IS DISTINCT FROM o.value;

    IF diff IS NOT NULL THEN
        INSERT INTO change_log (run_id, table_name, record_key, change_type, changed_fields)
        VALUES (
            nullif(current_setting('app.run_id', true), '')::uuid,
            TG_TABLE_NAME,
            (SELECT jsonb_object_agg(k, to_jsonb(NEW) -> k) FROM unnest(TG_ARGV) AS k),
            'UPDATE',
            diff
        );
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

-- -------------------------------------------------------------
-- 5. Attach the trigger to all 8 tables (key columns = primary key)
-- -------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_log_changes ON supplier;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON supplier
    FOR EACH ROW EXECUTE FUNCTION log_changes('supplier');

DROP TRIGGER IF EXISTS trg_log_changes ON supplier_company;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON supplier_company
    FOR EACH ROW EXECUTE FUNCTION log_changes('supplier', 'company_code');

DROP TRIGGER IF EXISTS trg_log_changes ON supplier_purchasing_org;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON supplier_purchasing_org
    FOR EACH ROW EXECUTE FUNCTION log_changes('supplier', 'purchasing_organization');

DROP TRIGGER IF EXISTS trg_log_changes ON supplier_text;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON supplier_text
    FOR EACH ROW EXECUTE FUNCTION log_changes('supplier', 'language', 'text_type');

DROP TRIGGER IF EXISTS trg_log_changes ON purchase_order;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON purchase_order
    FOR EACH ROW EXECUTE FUNCTION log_changes('purchase_order');

DROP TRIGGER IF EXISTS trg_log_changes ON purchase_order_item;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON purchase_order_item
    FOR EACH ROW EXECUTE FUNCTION log_changes('purchase_order', 'purchase_order_item');

DROP TRIGGER IF EXISTS trg_log_changes ON supplier_invoice;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON supplier_invoice
    FOR EACH ROW EXECUTE FUNCTION log_changes('supplier_invoice', 'fiscal_year');

DROP TRIGGER IF EXISTS trg_log_changes ON invoice_po_reference;
CREATE TRIGGER trg_log_changes AFTER UPDATE ON invoice_po_reference
    FOR EACH ROW EXECUTE FUNCTION log_changes(
        'supplier_invoice', 'fiscal_year', 'purchase_order',
        'purchase_order_item', 'supplier_invoice_item');
