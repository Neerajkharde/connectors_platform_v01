# SAP S/4HANA → PostgreSQL Connector

A Python-based connector that extracts Supplier, Purchase Order, Purchase Order Item, Supplier Invoice, and Invoice-to-PO Reference data from SAP S/4HANA OData APIs and persists it in PostgreSQL while preserving all ERD-defined relationships.

## Architecture

```
SAP S/4HANA APIs                      PostgreSQL
──────────────────                     ──────────
A_Supplier (OData V2 XML)        →    supplier
  └─ to_SupplierCompany          →    supplier_company
  └─ to_SupplierPurchasingOrg    →    supplier_purchasing_org
  └─ to_SupplierText             →    supplier_text
PurchaseOrder (OData V4 JSON)    →    purchase_order
PurchaseOrderItem (OData V4)     →    purchase_order_item
A_SupplierInvoice (OData V2)     →    supplier_invoice
A_SuplrInvcItemPurOrdRef (V2)    →    invoice_po_reference
```

### How a run works

```
Stage 1   suppliers (+ company / purchasing-org / text)       -> upsert -> COMMIT
Stage 2   purchase orders in resumable batches (per batch):
            next POs -> their items -> their invoice refs & headers
            -> integrity check -> upsert -> advance PO cursor -> COMMIT
Verify    record counts + relationship queries
```

Every run is **incremental**: it only asks SAP for records that are new or changed since the last run
(see [Incremental Sync](#incremental-sync)). Every stage / batch is committed on its own, so a quota
error never throws away finished work.

## Prerequisites

- **Python 3.10+**
- **PostgreSQL 13+** running and accessible
- **SAP S/4HANA** system or SAP API Business Hub sandbox access

## Setup

### 1. Clone and install dependencies

```bash
cd sap-postgres-connector
pip install -r requirements.txt
```

### 2. Create the PostgreSQL database and schema

```sql
-- Connect to PostgreSQL and create the database
CREATE DATABASE sap_connector;

-- Then apply the schema
\c sap_connector
\i sql/schema.sql
```

Or from the command line:

```bash
createdb sap_connector
psql -d sap_connector -f sql/schema.sql
```

The tables for incremental sync (`sync_state`, `supplier_po_cursor`, `run_log`, `change_log` and the
change-logging triggers) are created **automatically** at the start of every run from
`sql/incremental.sql` - you do not need to run it by hand (it is safe to run repeatedly).

> `sql/schema.sql` drops and re-creates the 8 data tables **and** the cursor tables
> (`sync_state`, `supplier_po_cursor`), because the cursors describe what is in those tables.
> `run_log` and `change_log` are history and are kept.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` (all options are documented in `.env.example`):

```env
# SAP connection
SAP_BASE_URL=https://sandbox.api.sap.com/s4hanacloud
SAP_API_KEY=your-api-key
SAP_AUTH_MODE=apikey

# PostgreSQL connection
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=sap_connector
PG_USER=postgres
PG_PASSWORD=your-password
```

**Auth modes:**
- `apikey` — sends `APIKey: <key>` header (**required** for the SAP API Business Hub sandbox)
- `basic` — sends HTTP Basic Auth (for on-premise / BTP systems)
- `none` — no authentication

**Limits and incremental settings** (all optional, defaults shown):

```env
SUPPLIER_TOP=800       # max suppliers fetched per RUN (the next run continues)
PO_TOP=5000            # max purchase orders per RUN - a budget, not a requirement
PO_BATCH=500           # POs per committed batch (PO -> items -> invoices -> commit)
ITEM_TOP=20000         # safety cap on items per batch
INVOICE_TOP=5000       # safety cap on invoice references / headers

INCREMENTAL=true       # false = old behaviour: always fetch from the start
FULL_REFRESH=false     # true  = ignore the cursors for this run only
SUPPLIER_DATE_FIELD=CreationDate        SUPPLIER_DATE_TYPE=date
PO_DATE_FIELD=LastChangeDateTime        PO_DATE_TYPE=datetimeoffset
```

**Request behaviour** (`SAP_PAGE_SIZE`, `SAP_FILTER_CHUNK`, `SAP_USE_EXPAND`,
`SAP_REQUEST_DELAY`, `SAP_MAX_RETRIES`, `SAP_TIMEOUT`) is explained in `.env.example`.
`SUPPLIER_TOP` and `PO_TOP` are budgets **per run**: when one is used up the run stops cleanly and the next
run continues from where it stopped.

## Execution

Run the complete extraction from the project root:

```bash
python -m app.main
```

The script will:
1. Connect to SAP and PostgreSQL, apply `sql/incremental.sql`, and start a run (`run_log` row + run id)
2. **Stage 1** - fetch suppliers with their company / purchasing-org / text records (`$expand`, paged),
   starting after the supplier cursor; map, check integrity, upsert, advance the cursor, **commit**
3. **Stage 2** - load purchase orders in batches. For each batch: fetch the next POs after the PO cursor
   of a group of suppliers, their items, and their invoice references and headers; map; check referential
   integrity (against this batch **and** the database); upsert in FK order; advance the PO cursors; **commit**.
   The stage stops when `PO_TOP` POs were loaded in this run - the next run continues
4. Print record counts and run relationship-verification queries

Rows are **upserted**: new rows are inserted, changed rows are updated (and logged in `change_log`),
identical rows are left untouched. The number of SAP calls is printed after every stage and batch.

Re-run the command until the log no longer says `PO_TOP reached - N supplier(s) still to be scanned`.
After that, runs are tiny (about one call for suppliers plus one call per `SAP_FILTER_CHUNK` stored suppliers).

## Project Structure

```
sap-postgres-connector/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Environment / .env loader
│   ├── sap_client.py             # SAP HTTP client: throttle, retry, quota fail-fast
│   ├── odata.py                  # OData parsing, paging, $filter chunking helpers
│   ├── integrity.py              # FK-consistency check between mapping and insert
│   ├── db.py                     # PostgreSQL connection factory
│   ├── sync_state.py             # supplier cursor, PO cursors, run log, run-id tagging, known keys
│   ├── models.py                 # Python dataclasses for all 8 tables
│   ├── main.py                   # Orchestrator: stages, resumable PO batches, checkpoints
│   ├── connectors/
│   │   ├── supplier_connector.py       # Supplier API (OData V2), keyset paging
│   │   ├── purchase_order_connector.py # PO API (OData V4), resumable batch fetch
│   │   └── invoice_connector.py        # Invoice API (OData V2)
│   ├── mapping/
│   │   └── mappers.py            # SAP field → PostgreSQL column mappers
│   └── repositories/
│       └── repositories.py       # upsert logic (insert / update-if-changed) for all 8 tables
├── sql/
│   ├── schema.sql                # PostgreSQL DDL (8 data tables; drops data + cursor tables)
│   └── incremental.sql           # sync_state, supplier_po_cursor, run_log, change_log + triggers (auto-applied)
├── tests/
│   ├── test_mappers.py           # Unit tests for mapping functions
│   ├── test_odata.py             # OData parsing, paging, $filter helpers
│   ├── test_sap_client.py        # throttle / retry / quota behaviour
│   ├── test_connectors.py        # call counts, $expand fallback, quota propagation
│   ├── test_integrity.py         # FK-consistency check
│   ├── test_incremental_units.py # keyset filters, connectors, integrity with DB keys (no DB)
│   └── test_incremental_e2e.py   # full run vs. fake SAP + real PostgreSQL
├── diag_test.py                  # endpoint diagnostic (1 call per probe)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Database Schema (ERD)

The schema implements 8 tables with the following relationships:

| Parent Table         | Child Table             | Relationship |
|----------------------|-------------------------|--------------|
| supplier             | supplier_company        | 1 → N        |
| supplier             | supplier_purchasing_org | 1 → N        |
| supplier             | supplier_text           | 1 → N        |
| supplier             | purchase_order          | 1 → N        |
| supplier             | supplier_invoice        | 1 → N        |
| purchase_order       | purchase_order_item     | 1 → N        |
| purchase_order       | supplier_invoice        | 1 → N        |
| supplier_invoice     | invoice_po_reference    | 1 → N        |
| purchase_order_item  | invoice_po_reference    | 1 → N        |

Composite primary keys:
- `supplier_company`: (supplier, company_code)
- `supplier_purchasing_org`: (supplier, purchasing_organization)
- `supplier_text`: (supplier, language, text_type)
- `supplier_invoice`: (supplier_invoice, fiscal_year)
- `purchase_order_item`: (purchase_order, purchase_order_item)
- `invoice_po_reference`: (supplier_invoice, fiscal_year, purchase_order, purchase_order_item, supplier_invoice_item)

## Verification Queries

After a successful run, verify the data:

```sql
-- Record counts
SELECT 'supplier' AS tbl, COUNT(*) FROM supplier
UNION ALL SELECT 'supplier_company', COUNT(*) FROM supplier_company
UNION ALL SELECT 'supplier_purchasing_org', COUNT(*) FROM supplier_purchasing_org
UNION ALL SELECT 'supplier_text', COUNT(*) FROM supplier_text
UNION ALL SELECT 'purchase_order', COUNT(*) FROM purchase_order
UNION ALL SELECT 'purchase_order_item', COUNT(*) FROM purchase_order_item
UNION ALL SELECT 'supplier_invoice', COUNT(*) FROM supplier_invoice
UNION ALL SELECT 'invoice_po_reference', COUNT(*) FROM invoice_po_reference;

-- Supplier → PO → PO Item → Invoice reference chain
SELECT s.supplier, s.supplier_name,
       po.purchase_order, poi.purchase_order_item,
       ipr.supplier_invoice, ipr.fiscal_year
FROM supplier s
JOIN purchase_order po ON po.supplier = s.supplier
JOIN purchase_order_item poi ON poi.purchase_order = po.purchase_order
JOIN invoice_po_reference ipr
     ON ipr.purchase_order = poi.purchase_order
    AND ipr.purchase_order_item = poi.purchase_order_item
LIMIT 10;
```

## SAP API Assumptions

| API | Protocol | Format | Notes |
|-----|----------|--------|-------|
| A_Supplier | OData V2 | XML/Atom | Navigation links for company, purch-org, text |
| PurchaseOrder | OData V4 | JSON | Filtered by Supplier |
| PurchaseOrderItem | OData V4 | JSON | Filtered by PurchaseOrder |
| A_SupplierInvoice | OData V2 | XML/Atom | Fetched by composite key (invoice + fiscal year) |
| A_SuplrInvcItemPurOrdRef | OData V2 | XML/Atom | Filtered by PurchaseOrder |

**Known gap:** Invoice header fields (e.g. `InvoiceGrossAmount`, `PostingDate`) are fetched from `A_SupplierInvoice`. If this resource is not available in your SAP system, invoice headers will be skipped and the gap reported.

## Troubleshooting

### `policies.ratelimit.QuotaViolation` (HTTP 500)

```json
{"fault":{"faultstring":"Rate limit quota violation. Quota limit  exceeded...","detail":{"errorcode":"policies.ratelimit.QuotaViolation"}}}
```

The SAP API Business Hub gateway allows each API key only a limited number of calls and answers
with this error when it is used up (note: it uses HTTP **500**, not 429). This is a **server-side
limit — no code change can restore the quota**; you have to wait until it resets or use another key.

What the connector does about it:
- makes far fewer calls (grouped filters, `$expand`, paging) so a run fits in the quota;
- throttles calls (`SAP_REQUEST_DELAY`) and retries *temporary* errors (spike arrest, 503) with back-off;
- on a real quota error it **stops immediately** (exit code 2) and sends no further requests. Everything committed before the error stays (finished stages and batches, and the suppliers / POs fetched just before the error where safe); only the batch in flight is lost. Re-run after the quota resets and it **continues from the saved cursors**;
- `python diag_test.py` checks every endpoint with one call each and stops at the first quota error.

### `PO_TOP reached - N supplier(s) still to be scanned`
Not an error. `PO_TOP` is the number of POs one run may load; the rest is picked up by the next run.
Progress: compare `SELECT count(*) FROM supplier_po_cursor` with `SELECT count(*) FROM supplier`.

### `SAP rejected the supplier / PO date filter ...`
The date field in `SUPPLIER_DATE_FIELD` / `PO_DATE_FIELD` is not supported in `$filter` / `$orderby` (or its
`*_DATE_TYPE` is wrong). The connector falls back to a plain full fetch, so nothing is lost, but you do not
get the quota saving or resumability. Check the field on the API Business Hub page and fix the `.env` setting.

### `The data tables are empty but ... existed - reset`
The tables were truncated or re-created while the cursors survived. The app discards the (now false)
cursors and fetches everything again from the start.

### `UnicodeEncodeError: 'charmap' codec can't encode ...` (Windows)
Happened when output was redirected (`> file`, `| Out-File`) and the script printed a non-ASCII
character. The scripts now force UTF-8 output and use ASCII markers.

### Upgrading an existing database
`supplier_text.text` changed from `VARCHAR(255)` to `TEXT` (SAP long texts are longer and made the
whole load fail). Either re-run `sql/schema.sql` (drops and recreates all tables) or keep your data with:

```sql
ALTER TABLE supplier_text ALTER COLUMN text TYPE TEXT;
```

**Upgrading from the first incremental version** (supplier/PO watermarks only): nothing to do. At the next start the
app adds the `last_key` column to `sync_state` and creates `supplier_po_cursor`. Your existing supplier watermark is
kept (it is used without a key once, then with a key). Suppliers have no PO cursor yet, so their POs are scanned
once from the oldest; rows you already have arrive as "unchanged".

## Tests

```bash
python -m unittest discover -s tests -t .
```

The end-to-end tests (`tests/test_incremental_e2e.py`) run the real `app.main.run()` against a fake SAP server and a **real PostgreSQL** (connection from `PG_*` variables, default `postgres@localhost/sap_connector`). They are skipped automatically if PostgreSQL is unreachable. **They drop and re-create the connector tables in that database - point them at a test database.**

## Incremental Sync

A re-run no longer downloads everything again. The connector remembers how far it got and only asks SAP for records that are new or changed since then.

**How it works**

| Piece | What it does |
|---|---|
| `sync_state` table | The **supplier watermark**: the last `(date, Supplier)` loaded. |
| `supplier_po_cursor` table | A **PO cursor per supplier**: the last `(date, PurchaseOrder)` loaded. This is what makes the PO stage resumable. |
| SAP `$filter` | Rows are requested oldest-first (`$orderby <DateField> asc, <Key> asc`) and strictly *after* the cursor: `(F gt V) or (F eq V and Key gt 'k')`. This **keyset paging** keeps moving forward even if thousands of rows share one timestamp. (A cursor without a key, e.g. from an older version, uses `F ge V`.) |
| Upsert | `INSERT ... ON CONFLICT DO UPDATE ... WHERE <row> IS DISTINCT FROM <new row>`: new rows inserted, changed rows updated, identical rows untouched. |
| `change_log` table | A database trigger on all 8 tables records every UPDATE: which record, which columns, old and new value, and the run id. |
| `run_log` table | One row per run: status (`OK` / `QUOTA` / `FAILED`), SAP calls, inserted/updated/unchanged per table, and the rows the integrity step dropped (count + example keys). |
| Integrity vs. database | A child row is no longer dropped just because its parent was loaded by an *earlier* run; parents are looked up in PostgreSQL too. |
| Resumable batches | Suppliers are one committed stage. POs are loaded in **batches**: next `PO_BATCH` POs -> their items -> their invoices -> upsert -> advance the PO cursor -> COMMIT. `PO_TOP` is the budget of POs *per run*; when it is used up the run stops and the next run carries on. A quota error loses only the batch in flight. |

`sql/incremental.sql` creates the new tables and triggers. The app applies it automatically at the start of every run (it is idempotent). If you re-run `sql/schema.sql` (which drops the data tables), simply start the app once afterwards to re-attach the triggers.

**Settings (`.env`)**

```
INCREMENTAL=true            # false = old behaviour: always fetch from the start
FULL_REFRESH=false          # true  = ignore the watermarks for this run only
SUPPLIER_DATE_FIELD=CreationDate        SUPPLIER_DATE_TYPE=date
PO_DATE_FIELD=LastChangeDateTime        PO_DATE_TYPE=datetimeoffset
PO_TOP=2000                 # max POs per RUN (the run stops there; the next run continues)
PO_BATCH=500                # POs per committed batch (checkpoint)
```

The `*_DATE_FIELD` must be a field the SAP API supports in `$filter` / `$orderby` - check it on the API Business Hub page. If SAP rejects the filter or ordering, the connector prints a warning and falls back to a plain full fetch for that entity (nothing is lost, you just don't save quota or get resumability). `*_DATE_TYPE` is `date`, `datetime` or `datetimeoffset` (the OData literal type of that field).

**Reading the history**

```sql
-- what changed in a record, and when?
SELECT changed_at, changed_fields FROM change_log
WHERE table_name = 'supplier' AND record_key->>'supplier' = '1000' ORDER BY changed_at;

-- what did the last runs do?
SELECT started_at, status, mode, sap_calls, stats, dropped FROM run_log ORDER BY started_at DESC LIMIT 5;

-- everything one run changed
SELECT table_name, record_key, changed_fields FROM change_log WHERE run_id = '<run id>';
```

**Things to know (limitations)**

- **A date field only catches what it reflects.** `A_Supplier` normally has no "last changed" timestamp, so the default `CreationDate` finds *new* suppliers but not *edits* to old ones. If your system exposes a change timestamp for suppliers, set `SUPPLIER_DATE_FIELD` to it. Edits to a supplier's company / purchasing-org / text rows are only picked up when the supplier itself is re-fetched.
- **`PO_TOP` is a per-run budget, not a requirement.** Initial loads simply take several runs; each run continues where the previous one stopped. Suppliers never synced for POs are scanned first (oldest PO first).
- **The first PO run re-reads POs you already have.** Suppliers have no PO cursor yet, and POs loaded by older versions came in unordered, so they cannot be trusted to be gap-free. They arrive as "unchanged" (no change-log noise).
- **Once a supplier's POs are caught up** its cursor is set to "now minus 1 day" (covers clock differences with SAP). Later runs ask only for POs changed after that - typically one cheap call per group of `SAP_FILTER_CHUNK` suppliers.
- **PO fetching covers all suppliers stored in the database**, not only those fetched in this run.
- **Invoices are looked up for the POs of each batch.** A *new invoice on an unchanged, already-loaded PO* is not found until that PO changes or you run once with `FULL_REFRESH=true`.
- **`FULL_REFRESH=true`** ignores the cursors and starts from the oldest record, but is still limited by `PO_TOP` per run. Cursors only move forward, so afterwards a normal run continues from them.
- **Stale cursors are discarded.** If the data tables are empty but cursors exist (tables truncated), the app resets the cursors with a warning. `sql/schema.sql` also drops `sync_state` and `supplier_po_cursor` for the same reason.
- **Rows without a value in the date field** are only loaded by a from-the-beginning fetch; later changes to them are not detected by the date filter.
- **Deletes** are not detected (the connector never deletes). A deletion flag set in SAP arrives as an update and is logged.
- `change_log` grows without limit; archive or purge it as you see fit.

## Out of Scope (v1)

- Detecting deletions in SAP
- Retention / archiving of `change_log`
- Staging tables
- Monitoring / notifications
- Scheduling / orchestration
- Advanced validation and reconciliation


## Dated 03 Nov: Issue in the PO stage - fixed

**Status: resolved** by resumable PO batches with per-supplier cursors (see [Incremental Sync](#incremental-sync)).

### What was observed (first incremental version)

**Stage 2 (POs) is where it didn’t go as planned**

There is no PO watermark yet, so it fetched all POs for all 825 stored suppliers.

It hit PO_TOP=2000 after 2000 POs. One supplier (10300006) alone has 1665 POs, so the cap was reached within the first few chunks.

Result: 0 new, 2000 unchanged. These are the same 2000 POs as before, and the POs of your 225 new suppliers were probably never reached.

Because the cap was hit, the code deliberately did not save a PO watermark. It would have skipped POs.

**What was expected from here**

 - Suppliers: each run now continues from the watermark. The next run asks for CreationDate >= 2019-08-19 and gets the next batch of up to 600. It repeats until it reaches the present, after which runs are tiny.

 - POs: as it stands, every run repeats the same 2000 POs and spends about 100 calls for nothing. The PO watermark can only be set by a run that completes without hitting PO_TOP. That’s a chicken-and-egg problem, and your data triggers it.

  - **Proposed fix:** make the PO stage resumable the way suppliers are, with a checkpoint per batch, so a cap or quota stop saves its progress. That removes the need for one giant run.

### What changed

- **PO cursors per supplier** (table `supplier_po_cursor`) replace the single PO watermark. Each supplier remembers the last
  `(date, PurchaseOrder)` loaded, so a stop at any point is resumable.
- **Batches with a checkpoint each:** next `PO_BATCH` POs -> items -> invoices -> upsert -> cursor -> COMMIT.
  A quota error loses only the batch in flight.
- **`PO_TOP` is a budget per run**, not something that must be large enough to finish. Initial loads simply take several runs.
- **Keyset paging** `(F gt V) or (F eq V and Key gt 'k')` instead of `F ge V`, so thousands of POs (or suppliers) sharing one
  timestamp / date cannot stall paging. This matters for supplier 10300006 and for suppliers sharing one `CreationDate`.
- **Safety:** cursors that no longer match the data (tables emptied) are discarded automatically.

### What to expect on the next runs (after upgrading)

1. **Stage 1:** asks for `CreationDate >= 2019-08-19` (oldest first, up to `SUPPLIER_TOP`). Suppliers on the boundary day come back
   as "unchanged", the others are new; a new supplier cursor with a key is saved.
2. **Stage 2:** no supplier has a PO cursor yet, so POs are scanned from the oldest, in batches, until `PO_TOP` is used up. Many POs in
   the first batches are ones you already have and show as "unchanged" (no `change_log` noise). The run ends with
   `PO_TOP reached - N supplier(s) still to be scanned` - a normal, successful exit.
3. **Run again.** Each run moves forward by up to `PO_TOP` POs and `SUPPLIER_TOP` suppliers (about 170 SAP calls at `PO_TOP=2000`).
   When the "still to be scanned" line disappears you are caught up; from then on runs download almost nothing.
4. If you see `SAP rejected the ... date filter`, see Troubleshooting.
