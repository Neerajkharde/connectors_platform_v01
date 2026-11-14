import { Icons } from "./Icons";

export function Topbar({ activeTab, health, onSyncClick }) {
  const tabTitles = {
    overview: "System Overview",
    explore: "Database Explorer",
    extract: "Data Extraction & Pipeline",
    connectors: "Active Connectors",
    history: "Extraction History & Watermarks",
    lineage: "End-to-End Data Lineage",
  };

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="breadcrumbs">
          <span className="breadcrumb-root">Enable</span>
          <span className="breadcrumb-separator">/</span>
          <span className="breadcrumb-current">{tabTitles[activeTab] || activeTab}</span>
        </div>
      </div>

      <div className="topbar-right">
        <div className="service-pill" title="FastAPI REST Backend">
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#0284c7" }} />
          <span>FastAPI :8000</span>
        </div>

        <div className="service-pill" title="PostgreSQL Target Database">
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: health.state === "online" ? "#10b981" : "#ef4444",
            }}
          />
          <span>PostgreSQL :5432</span>
        </div>

        <button className="btn btn-primary btn-sm" onClick={onSyncClick}>
          <Icons.Extract />
          <span>Sync Pipeline</span>
        </button>
      </div>
    </header>
  );
}
