import { Icons } from "../components/Icons";

export function LineagePage() {
  return (
    <div className="lineage-flow-container">
      <div className="page-header">
        <h2 className="page-title">End-to-End Data Lineage</h2>
        <p className="page-description">
          Visual mapping of SAP S/4HANA OData collections through stage extractors into PostgreSQL relational tables.
        </p>
      </div>

      {/* Stage 1: Suppliers */}
      <div className="lineage-stage-box">
        <div className="lineage-stage-header">
          <span className="stage-badge">Stage 1</span>
          <h3 style={{ fontSize: "16px", fontWeight: 700 }}>Supplier Master Data Integration</h3>
        </div>
        <div className="lineage-mapping-grid">
          <div className="source-api-card">
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#0284c7" }}>SAP OData V2 Service</span>
            <strong>A_Supplier</strong>
            <span style={{ fontSize: "12px", color: "#64748b" }}>Atom XML with $expand navigation</span>
          </div>
          <div className="mapping-arrow"><Icons.ArrowRight /></div>
          <div className="target-db-card">
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#166534" }}>PostgreSQL Target Tables</span>
            <div>
              <code style={{ marginRight: 6 }}>supplier</code>
              <code style={{ marginRight: 6 }}>supplier_company</code>
              <code style={{ marginRight: 6 }}>supplier_purchasing_org</code>
              <code>supplier_text</code>
            </div>
          </div>
        </div>
      </div>

      {/* Stage 2: Purchase Orders */}
      <div className="lineage-stage-box">
        <div className="lineage-stage-header">
          <span className="stage-badge" style={{ backgroundColor: "#2563eb" }}>Stage 2</span>
          <h3 style={{ fontSize: "16px", fontWeight: 700 }}>Purchase Orders & Line Items</h3>
        </div>
        <div className="lineage-mapping-grid">
          <div className="source-api-card">
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#2563eb" }}>SAP OData V4 Service</span>
            <strong>PurchaseOrder / PurchaseOrderItem</strong>
            <span style={{ fontSize: "12px", color: "#64748b" }}>JSON format with grouped batch OR-filters</span>
          </div>
          <div className="mapping-arrow"><Icons.ArrowRight /></div>
          <div className="target-db-card">
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#166534" }}>PostgreSQL Target Tables</span>
            <div>
              <code style={{ marginRight: 6 }}>purchase_order</code>
              <code>purchase_order_item</code>
            </div>
          </div>
        </div>
      </div>

      {/* Stage 3: Invoices */}
      <div className="lineage-stage-box">
        <div className="lineage-stage-header">
          <span className="stage-badge" style={{ backgroundColor: "#7e22ce" }}>Stage 3</span>
          <h3 style={{ fontSize: "16px", fontWeight: 700 }}>Supplier Invoices & References</h3>
        </div>
        <div className="lineage-mapping-grid">
          <div className="source-api-card">
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#7e22ce" }}>SAP OData V2 Service</span>
            <strong>A_SupplierInvoice / A_SuplrInvcItemPurOrdRef</strong>
            <span style={{ fontSize: "12px", color: "#64748b" }}>Atom XML with composite key batches</span>
          </div>
          <div className="mapping-arrow"><Icons.ArrowRight /></div>
          <div className="target-db-card">
            <span style={{ fontSize: "11px", fontWeight: 700, color: "#166534" }}>PostgreSQL Target Tables</span>
            <div>
              <code style={{ marginRight: 6 }}>supplier_invoice</code>
              <code>invoice_po_reference</code>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
