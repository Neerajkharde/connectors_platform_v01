-- =============================================================
-- SAP S/4HANA to PostgreSQL — Database Schema
-- Based on ERD: SAP Suppliers, Purchase Orders and Invoices
-- =============================================================

-- Drop tables in reverse dependency order (if re-creating)
DROP TABLE IF EXISTS invoice_po_reference CASCADE;
DROP TABLE IF EXISTS supplier_invoice CASCADE;
DROP TABLE IF EXISTS purchase_order_item CASCADE;
DROP TABLE IF EXISTS purchase_order CASCADE;
DROP TABLE IF EXISTS supplier_text CASCADE;
DROP TABLE IF EXISTS supplier_purchasing_org CASCADE;
DROP TABLE IF EXISTS supplier_company CASCADE;
DROP TABLE IF EXISTS supplier CASCADE;

-- 1. SUPPLIER
CREATE TABLE supplier (
    supplier                          VARCHAR(10)   NOT NULL,
    supplier_name                     VARCHAR(100),
    supplier_full_name                VARCHAR(255),
    supplier_account_group            VARCHAR(4),
    alternative_payee_account_number  VARCHAR(10),
    authorization_group               VARCHAR(4),
    business_partner_pan_number       VARCHAR(20),
    customer                          VARCHAR(10),
    payment_is_blocked_for_supplier   BOOLEAN,
    posting_is_blocked                BOOLEAN,
    purchasing_is_blocked             BOOLEAN,
    vat_registration                  VARCHAR(20),
    deletion_indicator                BOOLEAN,
    created_by_user                   VARCHAR(12),
    creation_date                     DATE,
    last_change_date_time             TIMESTAMP,
    CONSTRAINT pk_supplier PRIMARY KEY (supplier)
);

-- 2. SUPPLIER_COMPANY
CREATE TABLE supplier_company (
    supplier                VARCHAR(10)   NOT NULL,
    company_code            VARCHAR(4)    NOT NULL,
    company_name            VARCHAR(100),
    company_address         VARCHAR(255),
    deletion_indicator      BOOLEAN,
    created_by_user         VARCHAR(12),
    creation_date           DATE,
    last_change_date_time   TIMESTAMP,
    CONSTRAINT pk_supplier_company PRIMARY KEY (supplier, company_code),
    CONSTRAINT fk_supplier_company_supplier
        FOREIGN KEY (supplier) REFERENCES supplier (supplier)
);

-- 3. SUPPLIER_PURCHASING_ORG
CREATE TABLE supplier_purchasing_org (
    supplier                  VARCHAR(10)   NOT NULL,
    purchasing_organization   VARCHAR(4)    NOT NULL,
    purchasing_org_name       VARCHAR(100),
    deletion_indicator        BOOLEAN,
    created_by_user           VARCHAR(12),
    creation_date             DATE,
    last_change_date_time     TIMESTAMP,
    CONSTRAINT pk_supplier_purchasing_org PRIMARY KEY (supplier, purchasing_organization),
    CONSTRAINT fk_supplier_purch_org_supplier
        FOREIGN KEY (supplier) REFERENCES supplier (supplier)
);

-- 4. SUPPLIER_TEXT
CREATE TABLE supplier_text (
    supplier                VARCHAR(10)   NOT NULL,
    language                VARCHAR(2)    NOT NULL,
    text_type               VARCHAR(4)    NOT NULL,
    text                    VARCHAR(255),
    deletion_indicator      BOOLEAN,
    created_by_user         VARCHAR(12),
    creation_date           DATE,
    last_change_date_time   TIMESTAMP,
    CONSTRAINT pk_supplier_text PRIMARY KEY (supplier, language, text_type),
    CONSTRAINT fk_supplier_text_supplier
        FOREIGN KEY (supplier) REFERENCES supplier (supplier)
);

-- 5. PURCHASE_ORDER
CREATE TABLE purchase_order (
    purchase_order                      VARCHAR(10)   NOT NULL,
    supplier                            VARCHAR(10),
    purchase_order_type                 VARCHAR(4),
    purchase_order_subtype              VARCHAR(4),
    purchasing_document_origin          VARCHAR(4),
    purchasing_document_process_code    VARCHAR(4),
    created_by_user                     VARCHAR(12),
    creation_date                       DATE,
    purchase_order_date                 DATE,
    last_change_date_time               TIMESTAMP,
    validity_start_date                 DATE,
    validity_end_date                   DATE,
    msg_on_goods_receipt_is_required    BOOLEAN,
    company_code                        VARCHAR(4),
    purchasing_organization             VARCHAR(4),
    document_currency                   VARCHAR(5),
    deletion_indicator                  BOOLEAN,
    purchase_order_is_blocked           BOOLEAN,
    invoices_is_blocked                 BOOLEAN,
    goods_receipt_is_blocked            BOOLEAN,
    overall_release_status              VARCHAR(1),
    CONSTRAINT pk_purchase_order PRIMARY KEY (purchase_order),
    CONSTRAINT fk_purchase_order_supplier
        FOREIGN KEY (supplier) REFERENCES supplier (supplier)
);

-- 6. PURCHASE_ORDER_ITEM
CREATE TABLE purchase_order_item (
    purchase_order                  VARCHAR(10)     NOT NULL,
    purchase_order_item             VARCHAR(5)      NOT NULL,
    material                        VARCHAR(40),
    short_text                      VARCHAR(255),
    order_quantity                  DECIMAL(13,3),
    order_unit                      VARCHAR(3),
    net_price_amount                DECIMAL(15,2),
    net_price_unit                  VARCHAR(3),
    item_category                   VARCHAR(4),
    deletion_indicator              BOOLEAN,
    goods_receipt_is_expected       BOOLEAN,
    invoices_expected               BOOLEAN,
    plant                           VARCHAR(4),
    storage_location                VARCHAR(4),
    account_assignment_category     VARCHAR(1),
    cost_center                     VARCHAR(10),
    wbs_account                     VARCHAR(24),
    material_group                  VARCHAR(9),
    created_by_user                 VARCHAR(12),
    creation_date                   DATE,
    last_change_date_time           TIMESTAMP,
    CONSTRAINT pk_purchase_order_item PRIMARY KEY (purchase_order, purchase_order_item),
    CONSTRAINT fk_po_item_purchase_order
        FOREIGN KEY (purchase_order) REFERENCES purchase_order (purchase_order)
);

-- 7. SUPPLIER_INVOICE
CREATE TABLE supplier_invoice (
    supplier_invoice          VARCHAR(10)     NOT NULL,
    fiscal_year               VARCHAR(4)      NOT NULL,
    supplier                  VARCHAR(10),
    purchase_order            VARCHAR(10),
    company_code              VARCHAR(4),
    document_date             DATE,
    posting_date              DATE,
    invoicing_party           VARCHAR(10),
    document_currency         VARCHAR(5),
    invoice_gross_amount      DECIMAL(15,2),
    invoice_is_cancelled      BOOLEAN,
    overall_invoice_status    VARCHAR(1),
    created_by_user           VARCHAR(12),
    creation_date             DATE,
    last_change_date_time     TIMESTAMP,
    CONSTRAINT pk_supplier_invoice PRIMARY KEY (supplier_invoice, fiscal_year),
    CONSTRAINT fk_supplier_invoice_supplier
        FOREIGN KEY (supplier) REFERENCES supplier (supplier),
    CONSTRAINT fk_supplier_invoice_po
        FOREIGN KEY (purchase_order) REFERENCES purchase_order (purchase_order)
);

-- 8. INVOICE_PO_REFERENCE
CREATE TABLE invoice_po_reference (
    supplier_invoice          VARCHAR(10)     NOT NULL,
    fiscal_year               VARCHAR(4)      NOT NULL,
    purchase_order            VARCHAR(10)     NOT NULL,
    purchase_order_item       VARCHAR(5)      NOT NULL,
    supplier_invoice_item     VARCHAR(5)      NOT NULL,
    referenced_amount         DECIMAL(15,2),
    referenced_quantity       DECIMAL(13,3),
    document_currency         VARCHAR(5),
    deletion_indicator        BOOLEAN,
    created_by_user           VARCHAR(12),
    creation_date             DATE,
    last_change_date_time     TIMESTAMP,
    CONSTRAINT pk_invoice_po_reference
        PRIMARY KEY (supplier_invoice, fiscal_year, purchase_order, purchase_order_item, supplier_invoice_item),
    CONSTRAINT fk_inv_po_ref_invoice
        FOREIGN KEY (supplier_invoice, fiscal_year) REFERENCES supplier_invoice (supplier_invoice, fiscal_year),
    CONSTRAINT fk_inv_po_ref_po_item
        FOREIGN KEY (purchase_order, purchase_order_item) REFERENCES purchase_order_item (purchase_order, purchase_order_item)
);
