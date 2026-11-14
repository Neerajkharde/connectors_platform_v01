# SAP S/4HANA → PostgreSQL Connector & DataBridge Dashboard

A production-grade, Python-based connector and modern React web dashboard that extracts Supplier, Purchase Order, Purchase Order Item, Supplier Invoice, and Invoice-to-PO Reference data from SAP S/4HANA OData APIs (V2 XML & V4 JSON) and persists it into PostgreSQL while strictly preserving all ERD-defined relational integrity.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
  - [Data Integration Flow](#data-integration-flow)
  - [Web Application Architecture](#web-application-architecture)
  - [How an Extraction Run Works](#how-an-extraction-run-works)
- [Prerequisites](#prerequisites)
- [Setup & Installation](#setup--installation)
  - [1. Python Environment Setup](#1-python-environment-setup)
  - [2. PostgreSQL Database & Schema](#2-postgresql-database--schema)
  - [3. Configure Environment Variables](#3-configure-environment-variables)
- [Running the Connector](#running-the-connector)
  - [Option A: Command-Line Pipeline (CLI)](#option-a-command-line-pipeline-cli)
  - [Option B: Web Dashboard (FastAPI + React)](#option-b-web-dashboard-fastapi--react)
- [Web Dashboard Features](#web-dashboard-features)
- [REST API Reference](#rest-api-reference)
- [Database Schema & ERD](#database-schema--erd)
- [Incremental Sync & Keyset Architecture](#incremental-sync--keyset-architecture)
- [Data Verification Queries](#data-verification-queries)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Troubleshooting & FAQs](#troubleshooting--faqs)
- [Historical Fix Notes (03 Nov PO Stage)](#historical-fix-notes-03-nov-po-stage)

---

## Overview

Integrating SAP S/4HANA enterprise data into PostgreSQL often suffers from strict API rate limits, non-standard OData protocols, complex composite primary keys, and fragile multi-table foreign key dependencies.

This project solves these challenges with:
- **Resilient Multi-Protocol Connectors**: Consumes SAP Business Partner (OData V2 XML-Atom), Purchase Order (OData V4 JSON), and Supplier Invoice (OData V2 XML-Atom) APIs.
- **Stage-by-Stage Checkpoint Commits**: Each stage and batch commits independently to PostgreSQL. A server-side SAP quota limit error never discards already-completed work.
- **True Keyset Incremental Sync**: Uses `sync_state` watermarks and per-supplier `supplier_po_cursor` tracking with keyset ordering `(F gt V) or (F eq V and Key gt 'k')` to guarantee forward progress even when thousands of records share identical timestamps.
- **Database Trigger Audit Logging**: Automatically records every field-level row modification in `change_log` and every execution run in `run_log`.
- **Modern React + Vite Dashboard**: An enterprise web interface (DataBridge) to explore table schemas, inspect column constraints (PKs/FKs), preview live records, trigger sync pipelines, and export custom CSVs.

---

## Architecture

### Data Integration Flow

```
SAP S/4HANA APIs (OData V2 / V4)           PostgreSQL Relational Storage
─────────────────────────────────          ─────────────────────────────
A_Supplier (OData V2 XML-Atom)       ──►   supplier
  ├── to_SupplierCompany             ──►   supplier_company
  ├── to_SupplierPurchasingOrg       ──►   supplier_purchasing_org
  └── to_SupplierText                ──►   supplier_text

PurchaseOrder (OData V4 JSON)        ──►   purchase_order
PurchaseOrderItem (OData V4 JSON)    ──►   purchase_order_item

A_SupplierInvoice (OData V2 XML)     ──►   supplier_invoice
A_SuplrInvcItemPurOrdRef (V2 XML)    ──►   invoice_po_reference
```

### Web Application Architecture

```
┌────────────────────────────────┐
│   React Frontend (Vite :5173)   │
│   (DataBridge Web Dashboard)   │
└───────────────┬────────────────┘
                │ HTTP Requests / REST
                ▼
┌────────────────────────────────┐
│   FastAPI Backend (:8000)      │
│   (api.py — 19 Endpoints)      │
└───────┬────────────────┬───────┘
        │                │
        │ Direct SQL     │ Executes Pipeline
        ▼                ▼
┌──────────────┐   ┌────────────────────────────────┐
│  PostgreSQL  │   │  Python Connector Modules      │
│  (:5432)     │   │  (app/connectors/*, mappers)   │
└──────────────┘   └───────────────┬────────────────┘
                                   │ OData Calls
                                   ▼
                   ┌────────────────────────────────┐
                   │  SAP S/4HANA Cloud / Sandbox   │
                   └────────────────────────────────┘
```

### How an Extraction Run Works

```
Stage 1: Suppliers  ──► Fetch A_Supplier with $expand (company, org, text)
                        Map -> Enforce FK integrity -> Upsert -> Update Watermark -> COMMIT

Stage 2: PO Batches ──► In resumable batches (up to PO_BATCH per chunk):
                        Fetch next POs after per-supplier cursor -> Fetch PO items
                        Fetch Invoice references & headers -> Enforce referential integrity
                        Upsert in FK order -> Advance supplier_po_cursor -> COMMIT
                        (Stops cleanly when PO_TOP budget is reached; resumes next run)

Stage 3: Invoices   ──► Match invoice headers to PO item references -> Upsert -> COMMIT

Verification        ──► Check record counts, verify FK reference chains, log stats to run_log
```

Every run is **incremental**: it queries SAP only for records that are new or modified since the last saved watermark.

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+ & npm 9+** (for the React web dashboard)
- **PostgreSQL 13+** running and accessible
- **SAP S/4HANA System** or **SAP Business Accelerator Hub Sandbox** API Key

---

## Setup & Installation

### 1. Python Environment Setup

Clone the repository and install the backend dependencies:

```bash
cd sap-postgres-connector-staged
pip install -r requirements.txt
```

### 2. PostgreSQL Database & Schema

Connect to PostgreSQL and create the target database:

```sql
CREATE DATABASE sap_connector;
```

Apply the base DDL schema from `sql/schema.sql`:

```bash
# Using psql command line:
psql -d sap_connector -f sql/schema.sql
```

> **Note on Incremental Tables**:
> The tables for incremental sync (`sync_state`, `supplier_po_cursor`, `run_log`, `change_log`) and the database change-logging triggers are created **automatically** on every run from `sql/incremental.sql`. You do not need to execute `sql/incremental.sql` manually.
>
> `sql/schema.sql` drops and re-creates the 8 data tables and cursor tables. Historical audit tables (`run_log`, `change_log`) are preserved.

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your connection parameters:

```env
# ===================================================================
# SAP S/4HANA Connection
# ===================================================================
SAP_BASE_URL=https://sandbox.api.sap.com/s4hanacloud
SAP_API_KEY=your-api-key-here
SAP_AUTH_MODE=apikey

# ===================================================================
# PostgreSQL Connection
# ===================================================================
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=sap_connector
PG_USER=postgres
PG_PASSWORD=your-secure-password

# ===================================================================
# Incremental & Budget Settings (Optional defaults shown)
# ===================================================================
INCREMENTAL=true
FULL_REFRESH=false
SUPPLIER_TOP=800
PO_TOP=5000
PO_BATCH=500
ITEM_TOP=20000
INVOICE_TOP=5000

SUPPLIER_DATE_FIELD=CreationDate
SUPPLIER_DATE_TYPE=date
PO_DATE_FIELD=LastChangeDateTime
PO_DATE_TYPE=datetimeoffset

# ===================================================================
# Throttling & Network Resilience
# ===================================================================
SAP_PAGE_SIZE=50
SAP_FILTER_CHUNK=20
SAP_USE_EXPAND=true
SAP_REQUEST_DELAY=0.1
SAP_MAX_RETRIES=3
SAP_TIMEOUT=30
```

#### Authentication Modes (`SAP_AUTH_MODE`):
- `apikey` — Sends `APIKey: <key>` header (**required** for the SAP API Business Hub Sandbox).
- `basic` — Sends HTTP Basic Authentication (`SAP_USERNAME` and `SAP_PASSWORD`).
- `none` — Disables authentication headers (for mock servers or open proxies).

---

## Running the Connector

### Option A: Command-Line Pipeline (CLI)

To run the complete extraction pipeline directly from your terminal:

```bash
python -m app.main
```

The script will:
1. Initialize the PostgreSQL connection and automatically apply `sql/incremental.sql`.
2. Generate a unique `run_id` and create an entry in `run_log`.
3. **Stage 1**: Stream suppliers with associated companies, purchasing organizations, and texts via `$expand`, checking integrity and upserting into PostgreSQL.
4. **Stage 2**: Stream purchase orders and items in resumable batches using keyset cursors.
5. **Stage 3**: Fetch invoice cross-references and headers, dropping orphaned references to maintain referential integrity.
6. Verify record counts and print an execution summary.

Re-run the command until the log no longer displays `PO_TOP reached - N supplier(s) still to be scanned`. Future runs will only fetch delta changes.

---

### Option B: Web Dashboard (FastAPI + React)

The project includes an enterprise web dashboard for monitoring sync status, inspecting schemas, triggering extractions, and exporting data.

#### Step 1: Start the FastAPI Backend
From the project root:

```powershell
uvicorn api:app --reload
```
- **Backend URL**: `http://127.0.0.1:8000`
- **Interactive OpenAPI Docs**: `http://127.0.0.1:8000/docs`

#### Step 2: Start the React Frontend
In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```
- **Frontend URL**: `http://localhost:5173`

The Vite development server is configured with a built-in reverse proxy that forwards `/api/*` requests directly to `http://127.0.0.1:8000`.

---

## Web Dashboard Features

| Section | Capabilities |
|---|---|
| **System Overview** | Displays live KPI metrics (total tables, records persisted in PostgreSQL, active connectors, last sync status) and an interactive entity catalog grid. |
| **Database Explorer** | Inspects all 8 PostgreSQL tables. Switch between **Schema & Relationships** (columns, data types, primary keys, foreign key targets, descriptions) and **Data Preview** with adjustable row limits (10 to 100). |
| **Data Extraction** | Trigger live SAP extraction pipelines with a **Full Refresh** toggle and real-time status tracking. Also includes custom column selection with UTF-8 BOM CSV export. |
| **Active Connectors** | Displays metadata, protocols (`OData V2 XML` vs `OData V4 JSON`), endpoints, and resilience capabilities for Supplier, Purchase Order, and Invoice connectors. |
| **Sync History & Watermarks** | Inspects current keyset watermarks from `sync_state` and execution audit history from `run_log`. |
| **Data Lineage** | Visual diagram showing end-to-end data flow from SAP OData services into PostgreSQL relational tables. |

---

## REST API Reference

The FastAPI backend exposes 19 REST endpoints:

| Group | Method | Endpoint | Purpose |
|---|---|---|---|
| **Health** | GET | `/api/health` | Backend and PostgreSQL database connectivity check |
| **Connectors** | GET | `/api/connectors` | List all implemented SAP connectors with capabilities |
| **Connectors** | GET | `/api/connectors/{connector_id}` | Retrieve specific connector details |
| **Tables** | GET | `/api/tables` | List all 8 database tables with record counts |
| **Tables** | GET | `/api/tables/{table_name}/schema` | Complete table schema (columns, types, PKs, FKs, descriptions) |
| **Tables** | GET | `/api/tables/{table_name}/records` | Paginated records with optional search and limit |
| **Entities** | GET | `/api/entities` | List entities compatible with frontend catalog |
| **Entities** | GET | `/api/entities/{entity}/fields` | Column structure with dataclass fallback if DB offline |
| **Entities** | GET | `/api/entities/{entity}/records` | Preview records for a given entity |
| **SAP Entities** | GET | `/api/sap-entities` | SAP entities with mandatory vs. optional field breakdown |
| **SAP Entities** | GET | `/api/sap-entities/{entity_id}` | SAP entity details with enriched descriptions |
| **Extraction** | POST | `/api/extract` | Trigger asynchronous SAP extraction pipeline |
| **Extraction** | GET | `/api/extract/{extraction_id}` | Poll running extraction status and progress |
| **Extraction** | GET | `/api/extractions` | List current session extraction tasks |
| **History** | GET | `/api/history/runs` | List extraction runs from `run_log` |
| **History** | GET | `/api/history/runs/{run_id}` | Detailed run log entry with dropped record statistics |
| **History** | GET | `/api/history/changes` | Query audit `change_log` entries by table or run ID |
| **Sync State** | GET | `/api/sync-state` | Retrieve active incremental watermarks and PO cursor stats |
| **Dashboard** | GET | `/api/dashboard/stats` | Aggregated dashboard summary statistics |

> For comprehensive request/response payloads, see [`API_REFERENCE.md`](API_REFERENCE.md).

---

## Database Schema & ERD

The relational schema implements 8 tables with strict foreign key constraints:

| Parent Table | Child Table | Relationship | Cascade / Action |
|---|---|---|---|
| `supplier` | `supplier_company` | 1 → N | On Delete Cascade |
| `supplier` | `supplier_purchasing_org` | 1 → N | On Delete Cascade |
| `supplier` | `supplier_text` | 1 → N | On Delete Cascade |
| `supplier` | `purchase_order` | 1 → N | Enforced by Integrity Layer |
| `supplier` | `supplier_invoice` | 1 → N | Nullable link |
| `purchase_order` | `purchase_order_item` | 1 → N | On Delete Cascade |
| `purchase_order` | `supplier_invoice` | 1 → N | Referenced in invoice header |
| `purchase_order_item` | `invoice_po_reference` | 1 → N | On Delete Cascade |
| `supplier_invoice` | `invoice_po_reference` | 1 → N | Composite FK reference |

### Composite Primary Keys

- `supplier_company`: `(supplier, company_code)`
- `supplier_purchasing_org`: `(supplier, purchasing_organization)`
- `supplier_text`: `(supplier, language, text_type)`
- `purchase_order_item`: `(purchase_order, purchase_order_item)`
- `supplier_invoice`: `(supplier_invoice, fiscal_year)`
- `invoice_po_reference`: `(supplier_invoice, fiscal_year, purchase_order, purchase_order_item, supplier_invoice_item)`

---

## Incremental Sync & Keyset Architecture

Every sync run uses keyset pagination to avoid missing records:

| Mechanism | Description |
|---|---|
| **`sync_state` Table** | Tracks the global watermark for master entities: the last `(watermark_value, last_key)` processed. |
| **`supplier_po_cursor` Table** | Maintains an independent PO cursor per supplier: the last `(date, purchase_order)` synced. This allows PO batches to stop and resume cleanly. |
| **Keyset `$filter` Predicate** | Requests rows ordered oldest-first: `(DateField gt Value) or (DateField eq Value and Key gt 'last_key')`. Avoids pagination loops when multiple rows share the same timestamp. |
| **Idempotent Upsert** | Uses `INSERT ... ON CONFLICT DO UPDATE ... WHERE target IS DISTINCT FROM excluded`. Identical rows produce no database writes or change-log noise. |
| **`change_log` Triggers** | PostgreSQL triggers on all 8 tables record every `UPDATE`: records modified columns, old and new values, timestamp, and `run_id`. |
| **`run_log` History** | Records run mode (`INCREMENTAL` / `FULL_REFRESH`), status (`SUCCESS`, `QUOTA`, `FAILED`), SAP call counts, and dropped orphan records. |

### Querying the Audit History

```sql
-- View recent extraction runs and call counts
SELECT run_id, started_at, status, mode, sap_calls, stats
FROM run_log
ORDER BY started_at DESC
LIMIT 5;

-- Inspect field-level modifications made by a specific run
SELECT table_name, record_key, changed_fields, changed_at
FROM change_log
WHERE run_id = 'YOUR-RUN-ID-HERE'
ORDER BY changed_at;

-- Track changes made to a specific supplier over time
SELECT changed_at, changed_fields
FROM change_log
WHERE table_name = 'supplier' AND record_key->>'supplier' = '1000'
ORDER BY changed_at;
```

---

## Data Verification Queries

Execute these queries in PostgreSQL to verify data consistency after a run:

```sql
-- 1. Check record counts across all 8 tables
SELECT 'supplier' AS table_name, COUNT(*) FROM supplier
UNION ALL SELECT 'supplier_company', COUNT(*) FROM supplier_company
UNION ALL SELECT 'supplier_purchasing_org', COUNT(*) FROM supplier_purchasing_org
UNION ALL SELECT 'supplier_text', COUNT(*) FROM supplier_text
UNION ALL SELECT 'purchase_order', COUNT(*) FROM purchase_order
UNION ALL SELECT 'purchase_order_item', COUNT(*) FROM purchase_order_item
UNION ALL SELECT 'supplier_invoice', COUNT(*) FROM supplier_invoice
UNION ALL SELECT 'invoice_po_reference', COUNT(*) FROM invoice_po_reference;

-- 2. Verify complete relational chain: Supplier -> PO -> PO Item -> Invoice Reference
SELECT s.supplier,
       s.supplier_name,
       po.purchase_order,
       poi.purchase_order_item,
       poi.net_price_amount,
       poi.document_currency,
       ipr.supplier_invoice,
       ipr.fiscal_year,
       ipr.referenced_amount
FROM supplier s
JOIN purchase_order po ON po.supplier = s.supplier
JOIN purchase_order_item poi ON poi.purchase_order = po.purchase_order
JOIN invoice_po_reference ipr
     ON ipr.purchase_order = poi.purchase_order
    AND ipr.purchase_order_item = poi.purchase_order_item
LIMIT 10;
```

---

## Project Structure

```
sap-postgres-connector/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Configuration and environment loader
│   ├── db.py                     # PostgreSQL connection factory
│   ├── integrity.py              # Foreign key referential consistency enforcement
│   ├── main.py                   # CLI Orchestrator: stages, batches, checkpoints
│   ├── models.py                 # Python dataclasses mirroring the 8 schema tables
│   ├── odata.py                  # OData XML/JSON parsing, chunking, and paging
│   ├── sap_client.py             # SAP HTTP client: throttling, retry, quota handling
│   ├── sync_state.py             # Watermarks, PO cursors, and run log management
│   ├── connectors/
│   │   ├── supplier_connector.py       # Supplier API (OData V2 XML), $expand
│   │   ├── purchase_order_connector.py # PO & Items API (OData V4 JSON), batch OR
│   │   └── invoice_connector.py        # Invoice & Ref API (OData V2 XML)
│   ├── mapping/
│   │   └── mappers.py            # SAP payload -> Dataclass mappers
│   └── repositories/
│       └── repositories.py       # Idempotent upsert repositories for all 8 tables
├── frontend/                     # React + Vite Enterprise Web Dashboard
│   ├── public/                   # Static assets & icons
│   ├── src/
│   │   ├── App.jsx               # Main dashboard component
│   │   ├── App.css               # Clean enterprise styling
│   │   ├── index.css             # Base reset & design tokens
│   │   └── main.jsx              # Application entry point
│   ├── package.json              # Frontend dependencies (React 19, Vite)
│   └── vite.config.js            # Vite build configuration with /api proxy
├── sql/
│   ├── schema.sql                # Base DDL for the 8 relational data tables
│   └── incremental.sql           # sync_state, cursors, run_log, change_log triggers
├── tests/
│   ├── test_connectors.py        # Unit tests for connector API handling
│   ├── test_incremental_e2e.py   # Full pipeline E2E test with fake SAP + real PG
│   ├── test_incremental_units.py # Keyset filters and cursor unit tests
│   ├── test_integrity.py         # Referential integrity enforcement tests
│   ├── test_mappers.py           # Field mapping unit tests
│   ├── test_odata.py             # XML/JSON parsing and $filter chunking tests
│   └── test_sap_client.py        # Throttling, retry, and quota error propagation
├── api.py                        # FastAPI backend REST API (19 endpoints)
├── API_REFERENCE.md              # Complete REST endpoint specifications
├── diag_test.py                  # Single-call probe diagnostic utility
├── .env.example                  # Environment configuration template
├── requirements.txt              # Python runtime dependencies
└── README.md                     # Project documentation
```

---

## Testing

Run the test suite using Python's built-in `unittest` runner:

```bash
python -m unittest discover -s tests -t .
```

- **Unit Tests**: Test mappings, OData parser, integrity checks, and throttling without hitting SAP or PostgreSQL.
- **End-to-End Tests (`tests/test_incremental_e2e.py`)**: Runs `app.main.run()` against a mocked SAP server and a real PostgreSQL instance (configured via `PG_*` variables). If PostgreSQL is offline, E2E tests are safely skipped.

---

## Troubleshooting & FAQs

### 1. `policies.ratelimit.QuotaViolation` (HTTP 500)
```json
{"fault":{"faultstring":"Rate limit quota violation. Quota limit exceeded...","detail":{"errorcode":"policies.ratelimit.QuotaViolation"}}}
```
- **Cause**: The SAP API Business Hub gateway enforces daily call quotas per API key.
- **Resolution**: This is a server-side limit. The connector immediately halts execution (exit code 2) upon encountering this error. Because previous stages and batches were committed at checkpoints, **no finished work is lost**. Wait until your quota resets or supply a new `SAP_API_KEY` in `.env`, then re-run. Execution automatically resumes from the saved cursor.

### 2. `PO_TOP reached - N supplier(s) still to be scanned`
- **Cause**: Normal operational message. `PO_TOP` defines the maximum POs permitted per run to prevent timeout or quota exhaustion.
- **Resolution**: Re-run `python -m app.main`. The connector resumes scanning the remaining suppliers.

### 3. `SAP rejected the supplier / PO date filter`
- **Cause**: The SAP system does not support filtering or ordering on the specified `SUPPLIER_DATE_FIELD` or `PO_DATE_FIELD`.
- **Resolution**: Verify the field name against your SAP system metadata. The connector automatically falls back to a full fetch to prevent data loss.

### 4. `UnicodeEncodeError: 'charmap' codec can't encode...` (Windows)
- **Cause**: Windows PowerShell or Command Prompt using legacy code pages (e.g., CP1252) when redirecting output.
- **Resolution**: The connector forces UTF-8 stream output by default. If running custom scripts, set `$env:PYTHONIOENCODING="utf-8"`.

### 5. `ALTER TABLE supplier_text ALTER COLUMN text TYPE TEXT`
- **Cause**: SAP long texts exceeding standard `VARCHAR(255)` length limits.
- **Resolution**: In `sql/schema.sql`, `supplier_text.text` is defined as `TEXT`. If migrating an older database, execute:
  ```sql
  ALTER TABLE supplier_text ALTER COLUMN text TYPE TEXT;
  ```

---

## Historical Fix Notes (03 Nov PO Stage)

In earlier iterations, Stage 2 attempted to fetch purchase orders for all suppliers in a single monolithic run without a per-supplier cursor. When high-volume suppliers (e.g., vendor `10300006` with 1,600+ POs) were encountered, the run exhausted `PO_TOP` early, leaving later suppliers un-scanned and preventing a global watermark from being saved.

**Resolution Applied**:
1. **Per-Supplier Cursors (`supplier_po_cursor`)**: Replaced the monolithic watermark with independent tracking for each supplier's `(date, purchase_order)`.
2. **Resumable Batch Checkpoints**: POs are committed in configurable batches (`PO_BATCH=500`).
3. **Strict Keyset Paging**: Predicates use `(F gt V) or (F eq V and Key gt 'k')` to guarantee forward progression even when timestamps collide.
