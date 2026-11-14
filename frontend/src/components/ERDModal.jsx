import { useEffect, useState } from "react";
import { Icons } from "./Icons";

export function ERDModal({ isOpen, onClose }) {
  const [imageError, setImageError] = useState(false);
  const [activeTab, setActiveTab] = useState("diagram"); // "diagram" | "relationships"

  // Close on Escape key
  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const relationships = [
    { parent: "supplier", child: "supplier_company", type: "1 → N", key: "supplier" },
    { parent: "supplier", child: "supplier_purchasing_org", type: "1 → N", key: "supplier" },
    { parent: "supplier", child: "supplier_text", type: "1 → N", key: "supplier" },
    { parent: "supplier", child: "purchase_order", type: "1 → N", key: "supplier" },
    { parent: "supplier", child: "supplier_invoice", type: "1 → N", key: "supplier (nullable)" },
    { parent: "purchase_order", child: "purchase_order_item", type: "1 → N", key: "purchase_order" },
    { parent: "purchase_order", child: "supplier_invoice", type: "1 → N", key: "purchase_order (reference)" },
    { parent: "purchase_order_item", child: "invoice_po_reference", type: "1 → N", key: "purchase_order, purchase_order_item" },
    { parent: "supplier_invoice", child: "invoice_po_reference", type: "1 → N", key: "supplier_invoice, fiscal_year" },
  ];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-container" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div className="metric-icon-box blue" style={{ width: "30px", height: "30px" }}>
              <Icons.ERD />
            </div>
            <div>
              <h3 style={{ fontSize: "17px", fontWeight: 700, color: "#0f172a" }}>
                Entity-Relationship Diagram (ERD)
              </h3>
              <p style={{ fontSize: "12.5px", color: "#64748b" }}>
                Relational schema, composite primary keys, and foreign key dependencies across all 8 tables.
              </p>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <div className="subnav-tabs" style={{ marginBottom: 0, borderBottom: "none" }}>
              <button
                className={`subnav-tab-btn ${activeTab === "diagram" ? "active" : ""}`}
                onClick={() => setActiveTab("diagram")}
                style={{ padding: "6px 12px", fontSize: "12.5px" }}
              >
                <span>Diagram View</span>
              </button>
              <button
                className={`subnav-tab-btn ${activeTab === "relationships" ? "active" : ""}`}
                onClick={() => setActiveTab("relationships")}
                style={{ padding: "6px 12px", fontSize: "12.5px" }}
              >
                <span>Key Relations</span>
              </button>
            </div>

            <button className="modal-close-btn" onClick={onClose} title="Close (Esc)">
              &times;
            </button>
          </div>
        </div>

        <div className="modal-body">
          {activeTab === "diagram" && (
            <div className="erd-image-container">
              {!imageError ? (
                <img
                  src="/erd.png"
                  alt="Database Entity-Relationship Diagram (ERD)"
                  className="erd-image"
                  onError={() => setImageError(true)}
                />
              ) : (
                <div className="empty-box" style={{ padding: "40px 24px" }}>
                  <div className="metric-icon-box blue" style={{ width: "48px", height: "48px", margin: "0 auto 12px" }}>
                    <Icons.ERD />
                  </div>
                  <h4 style={{ fontSize: "15px", color: "#0f172a", marginBottom: "6px" }}>
                    ERD Image Placeholder
                  </h4>
                  <p style={{ maxWidth: "480px", margin: "0 auto 14px", lineHeight: "1.5" }}>
                    Place your ERD image file at <code>frontend/public/erd.png</code> to display your custom diagram here.
                  </p>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => setActiveTab("relationships")}
                  >
                    View Relational Schema Table &rarr;
                  </button>
                </div>
              )}
            </div>
          )}

          {activeTab === "relationships" && (
            <div className="table-wrapper">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Parent Table</th>
                    <th>Relationship</th>
                    <th>Child Table</th>
                    <th>Foreign Key Linking Columns</th>
                  </tr>
                </thead>
                <tbody>
                  {relationships.map((rel, idx) => (
                    <tr key={idx}>
                      <td><strong>{rel.parent}</strong></td>
                      <td><span className="pill-type">{rel.type}</span></td>
                      <td><strong>{rel.child}</strong></td>
                      <td><code>{rel.key}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <span style={{ fontSize: "12px", color: "#64748b" }}>
            Press <kbd style={{ padding: "2px 6px", background: "#f1f5f9", borderRadius: 4 }}>Esc</kbd> or click outside to close
          </span>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
