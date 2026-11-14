# API Reference — SAP S/4HANA → PostgreSQL Connector

Full REST API documentation for the FastAPI backend (`api.py`).

**Base URL:** `http://127.0.0.1:8000`
**Swagger UI:** `http://127.0.0.1:8000/docs`
**Start command:** `uvicorn api:app --reload`

---

## Endpoint Summary

| # | Method | Endpoint | Purpose | Frontend Section |
|---|--------|----------|---------|------------------|
| 1 | GET | `/api/health` | Backend + DB health check | All |
| 2 | GET | `/api/connectors` | List all SAP connectors | Connectors |
| 3 | GET | `/api/connectors/{id}` | Connector detail | Connectors |
| 4 | GET | `/api/tables` | List 8 DB tables with counts | Extraction History |
| 5 | GET | `/api/tables/{name}/schema` | Full schema: columns, types, PKs, FKs, descriptions | Extraction History |
| 6 | GET | `/api/tables/{name}/records` | Paginated records with search & sort | Extraction History |
| 7 | GET | `/api/entities` | List entities (existing frontend compat) | Extraction History |
| 8 | GET | `/api/entities/{entity}/fields` | Entity fields (existing frontend compat) | Extraction History |
| 9 | GET | `/api/entities/{entity}/records` | Entity records (existing frontend compat) | Extraction History |
| 10 | GET | `/api/sap-entities` | SAP entities with mandatory/optional fields | Dashboard |
| 11 | GET | `/api/sap-entities/{id}` | SAP entity detail + enriched field list | Dashboard |
| 12 | POST | `/api/extract` | Trigger data extraction | Dashboard |
| 13 | GET | `/api/extract/{id}` | Check extraction status | Dashboard |
| 14 | GET | `/api/extractions` | List all extractions (session) | Dashboard |
| 15 | GET | `/api/history/runs` | Extraction run log | Extraction History |
| 16 | GET | `/api/history/runs/{run_id}` | Run detail + change count | Extraction History |
| 17 | GET | `/api/history/changes` | Change log entries | Extraction History |
| 18 | GET | `/api/sync-state` | Watermarks & PO cursors | Dashboard |
| 19 | GET | `/api/dashboard/stats` | Summary statistics | Dashboard |

---

## 1. Health & Status

### `GET /api/health`

Check backend health and database connectivity.

**Response:**

```json
{
  "status": "healthy",
  "database": {
    "connected": true,
    "error": null,
    "tables_found": 8,
    "tables_expected": 8
  }
}
```

`status` is `"healthy"` when the database is reachable, `"degraded"` otherwise.

---

## 2. Connectors

### `GET /api/connectors`

List all SAP connectors implemented in the backend. Returns metadata derived from the actual connector modules in `app/connectors/`.

**Response:**

```json
{
  "connectors": [
    {
      "id": "supplier_connector",
      "name": "Supplier Connector",
      "module": "app.connectors.supplier_connector",
      "description": "Fetches supplier master data and related sub-entities ...",
      "sap_api": "A_Supplier (OData V2 / XML-Atom)",
      "protocol": "OData V2",
      "format": "XML / Atom",
      "data_fetched": "Supplier master records with company assignments, ...",
      "supported_entities": ["supplier", "supplier_company", "supplier_purchasing_org", "supplier_text"],
      "capabilities": [
        "Fetches suppliers with $expand for sub-collections in a single request",
        "Falls back to per-supplier navigation calls if $expand is rejected",
        "Supports incremental sync via keyset paging on CreationDate",
        "Handles SAP quota errors gracefully (saves partial results)",
        "Resumable: continues from saved watermark on next run"
      ],
      "status": "active"
    }
  ]
}
```

The three connectors returned:

| Connector | Module | SAP API | Data Fetched |
|-----------|--------|---------|--------------|
| Supplier Connector | `supplier_connector.py` | A_Supplier (V2 XML) | Suppliers + company / purch-org / text |
| Purchase Order Connector | `purchase_order_connector.py` | PurchaseOrder (V4 JSON) | PO headers + line items |
| Invoice Connector | `invoice_connector.py` | A_SupplierInvoice (V2 XML) | Invoice headers + PO references |

### `GET /api/connectors/{connector_id}`

Get detailed information about a specific connector.

**Path params:** `connector_id` — one of `supplier_connector`, `purchase_order_connector`, `invoice_connector`.

**404** if not found.

---

## 3. Database Tables (Extraction History)

### `GET /api/tables`

List all 8 database tables with their record counts.

**Response:**

```json
{
  "tables": [
    {
      "name": "supplier",
      "label": "Supplier",
      "description": "Master data for SAP suppliers/vendors. ...",
      "record_count": 825
    }
  ]
}
```

### `GET /api/tables/{table_name}/schema`

Get the full schema of a database table.

**Path params:** `table_name` — one of the 8 data tables.

**Response:**

```json
{
  "table": "supplier",
  "label": "Supplier",
  "description": "Master data for SAP suppliers/vendors. ...",
  "columns": [
    {
      "name": "supplier",
      "type": "VARCHAR(10)",
      "nullable": false,
      "primary_key": true,
      "foreign_key": null,
      "description": "SAP supplier number (A_Supplier key). Unique 10-character vendor ID.",
      "sap_entity": "A_Supplier"
    },
    {
      "name": "supplier_name",
      "type": "VARCHAR(100)",
      "nullable": true,
      "primary_key": false,
      "foreign_key": null,
      "description": "Short name of the supplier (SupplierName).",
      "sap_entity": "A_Supplier"
    }
  ]
}
```

Each column includes:
- **`type`** — display string like `VARCHAR(10)`, `DECIMAL(15,2)`, `TIMESTAMP`, `BOOLEAN`, `TEXT`
- **`primary_key`** / **`foreign_key`** — key classification; FK includes `{ referenced_table, referenced_column }`
- **`description`** — human-readable explanation of what the field represents
- **`sap_entity`** — which SAP OData entity / navigation property the field maps to

### `GET /api/tables/{table_name}/records`

Get paginated records from a database table with optional search and sorting.

**Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (1-based) |
| `page_size` | int | 50 | Records per page (1–500) |
| `search` | string | — | ILIKE search across all text/varchar columns |
| `sort_by` | string | — | Column to sort by |
| `sort_order` | string | `asc` | `asc` or `desc` |

**Response:**

```json
{
  "table": "supplier",
  "records": [ { "supplier": "0000001000", "supplier_name": "ABC Ltd", ... } ],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_records": 825,
    "total_pages": 17
  }
}
```

---

## 4. Entities (Existing Frontend Compatibility)

These endpoints match the contract the existing React `App.jsx` already uses.

### `GET /api/entities`

```json
{
  "entities": [
    { "name": "supplier", "entity": "supplier", "label": "Supplier", "description": "...", "record_count": 825 }
  ]
}
```

### `GET /api/entities/{entity}/fields`

```json
{
  "entity": "supplier",
  "fields": [
    { "name": "supplier", "type": "VARCHAR(10)", "nullable": false, "primary_key": true, "foreign_key": null, "description": "..." }
  ]
}
```

### `GET /api/entities/{entity}/records`

**Query params:** `limit` (default 50), `offset` (default 0).

```json
{
  "entity": "supplier",
  "records": [ { "supplier": "0000001000", ... } ]
}
```

---

## 5. SAP Entities (Dashboard — Configure Extraction)

### `GET /api/sap-entities`

List all SAP entities supported for extraction, with mandatory and optional field classification.

**Response:**

```json
{
  "entities": [
    {
      "id": "supplier",
      "name": "A_Supplier",
      "label": "Supplier Master",
      "description": "SAP Business Partner – Supplier master data ...",
      "sap_api": "A_Supplier (OData V2 / XML-Atom)",
      "tables": ["supplier", "supplier_company", "supplier_purchasing_org", "supplier_text"],
      "mandatory_fields": ["supplier"],
      "optional_fields": ["supplier_name", "supplier_full_name", "creation_date", "..."]
    }
  ]
}
```

The 5 SAP entities:

| Entity ID | SAP API | Target Tables |
|-----------|---------|---------------|
| `supplier` | A_Supplier (V2) | supplier, supplier_company, supplier_purchasing_org, supplier_text |
| `purchase_order` | PurchaseOrder (V4) | purchase_order |
| `purchase_order_item` | PurchaseOrderItem (V4) | purchase_order_item |
| `supplier_invoice` | A_SupplierInvoice (V2) | supplier_invoice |
| `invoice_po_reference` | A_SuplrInvcItemPurOrdRef (V2) | invoice_po_reference |

### `GET /api/sap-entities/{entity_id}`

Returns the same data as the list but with each field enriched with its `description`:

```json
{
  "id": "supplier",
  "name": "A_Supplier",
  "label": "Supplier Master",
  "fields": [
    { "name": "supplier", "mandatory": true, "description": "SAP supplier number (A_Supplier key). ..." },
    { "name": "supplier_name", "mandatory": false, "description": "Short name of the supplier (SupplierName)." }
  ]
}
```

**Mandatory fields** should appear greyed-out / disabled in the UI — they are always extracted.
**Optional fields** should appear as selectable checkboxes.

---

## 6. Data Extraction

### `POST /api/extract`

Trigger a data extraction from SAP S/4HANA. The extraction runs `app.main.run()` in a background thread.

**Request body:**

```json
{
  "entities": ["supplier", "purchase_order"],
  "selected_fields": {
    "supplier": ["supplier", "supplier_name", "creation_date"],
    "purchase_order": ["purchase_order", "supplier", "creation_date"]
  },
  "full_refresh": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entities` | `string[]` | Yes | Entity IDs to extract |
| `selected_fields` | `object` | No | Entity ID → list of field names (for frontend tracking) |
| `full_refresh` | `bool` | No | `true` = ignore watermarks for this run |

> **Important:** Field selection controls what the frontend shows/exports — it does **not** alter the database schema. All columns are always stored by the backend pipeline.

**Response:**

```json
{
  "extraction_id": "a1b2c3d4-...",
  "status": "running",
  "message": "Extraction started. Use GET /api/extract/{extraction_id} to check status."
}
```

### `GET /api/extract/{extraction_id}`

Check the status of a running or completed extraction.

```json
{
  "id": "a1b2c3d4-...",
  "status": "completed",
  "entities": ["supplier", "purchase_order"],
  "selected_fields": { ... },
  "full_refresh": false,
  "started_at": "2026-11-14T08:00:00",
  "finished_at": "2026-11-14T08:02:30",
  "error": null
}
```

`status` values: `"running"`, `"completed"`, `"failed"`.

### `GET /api/extractions`

List all extraction tasks from the current server session.

```json
{
  "extractions": [ { ... }, { ... } ]
}
```

---

## 7. Extraction History

### `GET /api/history/runs`

List extraction runs from the `run_log` table.

**Query params:** `limit` (default 20, max 100), `offset` (default 0).

**Response:**

```json
{
  "runs": [
    {
      "run_id": "a1b2c3d4-...",
      "started_at": "2026-11-14T07:58:00+00:00",
      "finished_at": "2026-11-14T08:02:30+00:00",
      "status": "OK",
      "mode": "incremental",
      "sap_calls": 47,
      "stats": {
        "supplier": { "inserted": 10, "updated": 2, "unchanged": 813 },
        "purchase_order": { "inserted": 50, "updated": 0, "unchanged": 1950 }
      },
      "dropped": {},
      "error": null
    }
  ],
  "total": 15
}
```

### `GET /api/history/runs/{run_id}`

Get details of a specific run, including the count of changes logged.

```json
{
  "run_id": "a1b2c3d4-...",
  "status": "OK",
  "changes_logged": 12,
  "...": "..."
}
```

### `GET /api/history/changes`

List change log entries with optional filtering.

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| `run_id` | string | Filter by run ID |
| `table_name` | string | Filter by table name |
| `limit` | int | Max results (default 50) |
| `offset` | int | Pagination offset |

**Response:**

```json
{
  "changes": [
    {
      "id": 42,
      "run_id": "a1b2c3d4-...",
      "table_name": "supplier",
      "record_key": { "supplier": "0000001000" },
      "change_type": "UPDATE",
      "changed_fields": {
        "supplier_name": { "old": "ABC Ltd", "new": "ABC Limited" }
      },
      "changed_at": "2026-11-14T08:01:15+00:00"
    }
  ],
  "total": 12
}
```

---

## 8. Sync State

### `GET /api/sync-state`

Get the current synchronization state: entity watermarks and PO cursor summary.

**Response:**

```json
{
  "watermarks": [
    {
      "entity": "supplier",
      "watermark_field": "CreationDate",
      "last_value": "2024-06-15T00:00:00",
      "last_key": "0000002500",
      "last_run_id": "a1b2c3d4-...",
      "updated_at": "2026-11-14T08:02:30+05:30"
    }
  ],
  "po_cursor_summary": {
    "total_suppliers": 700,
    "total_suppliers_in_db": 825,
    "oldest_cursor": "2018-01-15T10:30:00",
    "newest_cursor": "2026-11-13T23:00:00"
  }
}
```

---

## 9. Dashboard Stats

### `GET /api/dashboard/stats`

Get summary statistics for the dashboard overview page.

**Response:**

```json
{
  "tables": {
    "supplier": 825,
    "supplier_company": 1200,
    "supplier_purchasing_org": 950,
    "supplier_text": 3400,
    "purchase_order": 2000,
    "purchase_order_item": 8500,
    "supplier_invoice": 1500,
    "invoice_po_reference": 4200
  },
  "total_records": 22575,
  "last_run": {
    "run_id": "a1b2c3d4-...",
    "started_at": "2026-11-14T07:58:00+00:00",
    "finished_at": "2026-11-14T08:02:30+00:00",
    "status": "OK",
    "mode": "incremental",
    "sap_calls": 47
  },
  "connectors": 3,
  "sap_entities": 5
}
```

---

## Error Handling

All endpoints return standard HTTP status codes:

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid entity IDs, missing fields) |
| 404 | Resource not found (unknown table, connector, entity, run) |
| 500 | Server error (database unreachable, extraction failure) |

Error responses follow the format:

```json
{
  "detail": "Table 'foo' not found."
}
```

---

## CORS

The backend allows all origins (`*`) for development. Restrict this in production by editing the `CORSMiddleware` configuration in `api.py`.
