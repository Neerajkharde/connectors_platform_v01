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

**Request behaviour** (`SAP_PAGE_SIZE`, `SAP_FILTER_CHUNK`, `SAP_USE_EXPAND`,
`SAP_REQUEST_DELAY`, `SAP_MAX_RETRIES`, `SAP_TIMEOUT`) is explained in `.env.example`.
`SUPPLIER_TOP`, `PO_TOP`, `ITEM_TOP`, `INVOICE_TOP` are *overall* record limits per run.

## Execution

Run the complete extraction from the project root:

```bash
python -m app.main
```

The script will:
1. Connect to SAP and PostgreSQL
2. Fetch suppliers with their company / purchasing-org / text records (`$expand`, paged)
3. Fetch purchase orders and line items (grouped `$filter`, paged)
4. Fetch invoice-to-PO references and the invoice headers they point to (grouped, paged)
5. Map SAP fields to PostgreSQL columns
6. Check referential integrity (repairs / drops rows that would violate a foreign key and reports them)
7. Insert records in FK-dependency order inside a single transaction — only after *all* SAP data was fetched
8. Print record counts and run relationship-verification queries

The number of SAP calls is printed at the end of the fetch phase (roughly `suppliers / page_size`
plus a handful per entity type, instead of thousands).

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
│   ├── sync_state.py             # watermarks, run log, run-id tagging, known keys
│   ├── models.py                 # Python dataclasses for all 8 tables
│   ├── main.py                   # Orchestrator / CLI entry point
│   ├── connectors/
│   │   ├── supplier_connector.py       # Supplier API (OData V2)
│   │   ├── purchase_order_connector.py # PO API (OData V4)
│   │   └── invoice_connector.py        # Invoice API (OData V2)
│   ├── mapping/
│   │   └── mappers.py            # SAP field → PostgreSQL column mappers
│   └── repositories/
│       └── repositories.py       # upsert logic (insert / update-if-changed) for all 8 tables
├── sql/
│   ├── schema.sql                # PostgreSQL DDL (all 8 tables)
│   └── incremental.sql           # sync_state, run_log, change_log + change-logging triggers
├── tests/
│   ├── test_mappers.py           # Unit tests for mapping functions
│   ├── test_incremental_units.py # watermark filters, connectors, integrity (no DB)
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
- on a real quota error it **stops immediately** (exit code 2), sends no further requests and writes nothing to PostgreSQL;
- `python diag_test.py` checks every endpoint with one call each and stops at the first quota error.

### `UnicodeEncodeError: 'charmap' codec can't encode ...` (Windows)
Happened when output was redirected (`> file`, `| Out-File`) and the script printed a non-ASCII
character. The scripts now force UTF-8 output and use ASCII markers.

### Upgrading an existing database
`supplier_text.text` changed from `VARCHAR(255)` to `TEXT` (SAP long texts are longer and made the
whole load fail). Either re-run `sql/schema.sql` (drops and recreates all tables) or keep your data with:

```sql
ALTER TABLE supplier_text ALTER COLUMN text TYPE TEXT;
```

## Tests

```bash
python -m unittest discover -s tests -t .
```

The end-to-end tests (`tests/test_incremental_e2e.py`) run the real `app.main.run()` against a fake SAP server and a **real PostgreSQL** (connection from `PG_*` variables, default `postgres@localhost/sap_connector`). They are skipped automatically if PostgreSQL is unreachable. **They drop and re-create the connector tables in that database - point them at a test database.**

**Known gap:** Invoice header fields (e.g. `InvoiceGrossAmount`, `PostingDate`) are fetched from `A_SupplierInvoice`. If this resource is not available in your SAP system, invoice headers will be skipped and the gap reported.

## Incremental Sync

A re-run no longer downloads everything again. The connector remembers how far it got and only asks SAP for records that are new or changed since then.

**How it works**

| Piece | What it does |
|---|---|
| `sync_state` table | One **watermark** per entity (`supplier`, `purchase_order`): the highest date value loaded so far. |
| SAP `$filter` | The next run sends `<DateField> ge <watermark>` (plus `$orderby <DateField> asc`) so only new/changed rows are downloaded. `ge` (not `gt`) is deliberate: a few boundary rows are re-downloaded, which is harmless. |
| Upsert | `INSERT ... ON CONFLICT DO UPDATE ... WHERE <row> IS DISTINCT FROM <new row>`: new rows inserted, changed rows updated, identical rows untouched. |
| `change_log` table | A database trigger on all 8 tables records every UPDATE: which record, which columns, old and new value, and the run id. |
| `run_log` table | One row per run: status (`OK` / `QUOTA` / `FAILED`), SAP calls, inserted/updated/unchanged per table, and the rows the integrity step dropped (count + example keys). |
| Integrity vs. database | A child row is no longer dropped just because its parent was loaded by an *earlier* run; parents are looked up in PostgreSQL too. |
| Checkpoints | The run commits after each stage (suppliers, then POs + items, then invoices). A quota error in stage 2 keeps stage 1, and the rows fetched before the error are saved too. |

`sql/incremental.sql` creates the new tables and triggers. The app applies it automatically at the start of every run (it is idempotent). If you re-run `sql/schema.sql` (which drops the data tables), simply start the app once afterwards to re-attach the triggers.

**Settings (`.env`)**

```
INCREMENTAL=true            # false = old behaviour: always fetch from the start
FULL_REFRESH=false          # true  = ignore the watermarks for this run only
SUPPLIER_DATE_FIELD=CreationDate        SUPPLIER_DATE_TYPE=date
PO_DATE_FIELD=LastChangeDateTime        PO_DATE_TYPE=datetimeoffset
```

The `*_DATE_FIELD` must be a field the SAP API supports in `$filter` / `$orderby` - check it on the API Business Hub page. If SAP rejects the filter, the connector prints a warning and falls back to a full fetch for that entity (nothing is lost, you just don't save quota). `*_DATE_TYPE` is `date`, `datetime` or `datetimeoffset` (the OData literal type of that field).

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
- **Many records with the same date.** If more than `SUPPLIER_TOP` suppliers share the exact same watermark value (common in demo data with a single `CreationDate`), paging cannot move past them. Raise `SUPPLIER_TOP`.
- **`PO_TOP` must be large enough to finish a run.** The PO watermark only advances when every supplier chunk completed without hitting `PO_TOP`; otherwise a warning is printed and the watermark stays (so no PO is ever skipped).
- **PO fetching covers all suppliers stored in the database** (one call per `SAP_FILTER_CHUNK` suppliers per run), not only the suppliers fetched in this run. Suppliers seen for the first time get all of their POs; known suppliers get POs changed since the watermark.
- **Invoices are looked up for the POs fetched in this run.** A *new invoice on an unchanged PO* is not found until that PO changes or you run once with `FULL_REFRESH=true`.
- **Deletes** are not detected (the connector never deletes). A deletion flag set in SAP arrives as an update and is logged.
- `change_log` grows without limit; archive or purge it as you see fit.

## Out of Scope (v1)

- Detecting deletions in SAP
- Retention / archiving of `change_log`
- Staging tables
- Monitoring / notifications
- Scheduling / orchestration
- Advanced validation and reconciliation


## Dated 03 Nov : Issue to fix:
**Stage 2 (POs) is where it didn’t go as planned**

There is no PO watermark yet, so it fetched all POs for all 825 stored suppliers.

It hit PO_TOP=2000 after 2000 POs. One supplier (10300006) alone has 1665 POs, so the cap was reached within the first few chunks.

Result: 0 new, 2000 unchanged. These are the same 2000 POs as before, and the POs of your 225 new suppliers were probably never reached.

Because the cap was hit, the code deliberately did not save a PO watermark. It would have skipped POs.

**What was expected from here**

 - Suppliers: each run now continues from the watermark. The next run asks for CreationDate >= 2019-08-19 and gets the next batch of up to 600. It repeats until it reaches the present, after which runs are tiny.

 - POs: as it stands, every run repeats the same 2000 POs and spends about 100 calls for nothing. The PO watermark can only be set by a run that completes without hitting PO_TOP. That’s a chicken-and-egg problem, and your data triggers it.

  - **Fix:** make the PO stage resumable the way suppliers are, with a checkpoint per batch, so a cap or quota stop saves its progress. That removes the need for one giant run.