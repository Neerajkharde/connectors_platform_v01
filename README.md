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

Edit `.env`:

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
- `apikey` — sends `APIKey: <key>` header (for SAP API Business Hub sandbox)
- `basic` — sends HTTP Basic Auth (for on-premise / BTP systems)

## Execution

Run the complete extraction from the project root:

```bash
python -m app.main
```

The script will:
1. Connect to SAP and PostgreSQL
2. Fetch all suppliers and their related company / purchasing-org / text records
3. Fetch purchase orders and line items for each supplier
4. Fetch invoice headers and invoice-to-PO references for each PO
5. Map SAP fields to PostgreSQL columns
6. Insert records in FK-dependency order inside a single transaction
7. Print record counts and run relationship-verification queries

## Project Structure

```
sap-postgres-connector/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Environment / .env loader
│   ├── sap_client.py             # SAP HTTP client (OData V2 XML + V4 JSON)
│   ├── db.py                     # PostgreSQL connection factory
│   ├── models.py                 # Python dataclasses for all 8 tables
│   ├── main.py                   # Orchestrator / CLI entry point
│   ├── connectors/
│   │   ├── supplier_connector.py       # Supplier API (OData V2)
│   │   ├── purchase_order_connector.py # PO API (OData V4)
│   │   └── invoice_connector.py        # Invoice API (OData V2)
│   ├── mapping/
│   │   └── mappers.py            # SAP field → PostgreSQL column mappers
│   └── repositories/
│       └── repositories.py       # INSERT logic for all 8 tables
├── sql/
│   └── schema.sql                # PostgreSQL DDL (all 8 tables)
├── tests/
│   └── test_mappers.py           # Unit tests for mapping functions
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

## Out of Scope (v1)

- Incremental sync / change detection
- Retry policies / exponential backoff
- Staging tables
- Monitoring / notifications
- Scheduling / orchestration
- Advanced validation and reconciliation
