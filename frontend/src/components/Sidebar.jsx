import { Icons } from "./Icons";

export function Sidebar({ activeTab, onSelectTab, entitiesCount, health, onVerifyHealth }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand-wrapper">
          <div className="brand-logo-icon">E</div>
          <div className="brand-text">
            <span className="brand-title">Enable</span>
            <span className="brand-subtitle">Connectors Platform</span>
          </div>
        </div>
      </div>

      <nav className="sidebar-nav">
        <span className="nav-section-title">Workspace</span>

        <button
          className={`nav-link ${activeTab === "overview" ? "active" : ""}`}
          onClick={() => onSelectTab("overview")}
        >
          <span className="nav-link-icon"><Icons.Overview /></span>
          <span>Overview</span>
        </button>

        <button
          className={`nav-link ${activeTab === "explore" ? "active" : ""}`}
          onClick={() => onSelectTab("explore")}
        >
          <span className="nav-link-icon"><Icons.Database /></span>
          <span>Database Explorer</span>
          <span className="nav-link-badge">{entitiesCount}</span>
        </button>

        <button
          className={`nav-link ${activeTab === "extract" ? "active" : ""}`}
          onClick={() => onSelectTab("extract")}
        >
          <span className="nav-link-icon"><Icons.Extract /></span>
          <span>Data Extraction</span>
        </button>

        <span className="nav-section-title" style={{ marginTop: "12px" }}>Management</span>

        <button
          className={`nav-link ${activeTab === "connectors" ? "active" : ""}`}
          onClick={() => onSelectTab("connectors")}
        >
          <span className="nav-link-icon"><Icons.Connectors /></span>
          <span>Connectors</span>
          <span className="nav-link-badge">3</span>
        </button>

        <button
          className={`nav-link ${activeTab === "history" ? "active" : ""}`}
          onClick={() => onSelectTab("history")}
        >
          <span className="nav-link-icon"><Icons.History /></span>
          <span>Sync History</span>
        </button>

        <button
          className={`nav-link ${activeTab === "lineage" ? "active" : ""}`}
          onClick={() => onSelectTab("lineage")}
        >
          <span className="nav-link-icon"><Icons.Lineage /></span>
          <span>Data Lineage</span>
        </button>
      </nav>

      <div className="sidebar-footer">
        <div className="system-status-widget">
          <div className="status-widget-header">
            <span className="status-widget-label">System State</span>
            <div className="status-indicator-pill">
              <span className={`status-pulse-dot ${health.state}`} />
              <span style={{ color: health.state === "online" ? "#10b981" : health.state === "warning" ? "#f59e0b" : "#ef4444" }}>
                {health.state === "online" ? "Active" : health.state === "warning" ? "Degraded" : "Offline"}
              </span>
            </div>
          </div>
          <div className="status-widget-text" title={health.label}>
            {health.label}
          </div>
        </div>

        <button className="test-connection-btn" onClick={onVerifyHealth}>
          <Icons.Refresh />
          <span>Verify Connectivity</span>
        </button>
      </div>
    </aside>
  );
}
