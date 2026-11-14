export function ConnectorsPage({ connectors, loadingConnectors }) {
  return (
    <div>
      <div className="page-header">
        <h2 className="page-title">SAP S/4HANA Connectors</h2>
        <p className="page-description">
          Independent connector modules managing OData V2/V4 calls, pagination, batching, and quota resilience.
        </p>
      </div>

      {loadingConnectors ? (
        <div className="empty-box">
          <div className="spinner" />
          <span>Loading connector definitions...</span>
        </div>
      ) : (
        <div className="connector-card-grid">
          {connectors.map((c) => (
            <div key={c.id} className="connector-card">
              <div className="connector-header">
                <span className="connector-title">{c.name}</span>
                <span className="tag-badge" style={{ background: "#dcfce7", color: "#166534" }}>
                  ACTIVE
                </span>
              </div>

              <p className="connector-desc">{c.description}</p>

              <div className="connector-specs">
                <div><strong>SAP Service:</strong> <code>{c.sap_api}</code></div>
                <div><strong>Protocol:</strong> {c.protocol} ({c.format})</div>
                <div>
                  <strong>Tables:</strong>{" "}
                  {c.supported_entities.map((t) => (
                    <code key={t} style={{ marginRight: 4 }}>{t}</code>
                  ))}
                </div>
              </div>

              <div style={{ fontSize: "12px", fontWeight: 600, color: "#64748b", marginBottom: "6px" }}>
                KEY CAPABILITIES
              </div>
              <ul className="connector-capabilities-list">
                {c.capabilities.map((cap, i) => (
                  <li key={i}>{cap}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
