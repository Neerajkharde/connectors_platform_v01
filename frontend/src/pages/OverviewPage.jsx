import { Icons } from "../components/Icons";
import { formatDate } from "../utils/formatters";

export function OverviewPage({
  entities,
  loadingEntities,
  dashboardStats,
  onNavigate,
  onSelectEntity,
  onRefresh,
  onOpenERD,
}) {
  const totalRecords = dashboardStats?.total_records !== undefined
    ? dashboardStats.total_records
    : entities.reduce((acc, e) => acc + (e.record_count || 0), 0);

  return (
    <div>
      {/* Hero Welcome Card */}
      <div className="hero-card">
        <div className="hero-content">
          <span className="hero-badge-tag">S/4HANA OData Integration Engine</span>
          <h2>Enterprise Connector Dashboard</h2>
          <p>
            Orchestrates resilient batch synchronization from SAP S/4HANA OData V2 and V4
            services directly into PostgreSQL with ERD relationship preservation and keyset incremental cursors.
          </p>
          <div className="hero-actions">
            <button className="btn btn-primary" onClick={() => onNavigate("explore")}>
              <Icons.Database />
              <span>Explore Database Tables</span>
            </button>
            <button className="btn btn-secondary" onClick={() => onNavigate("extract")}>
              <Icons.Extract />
              <span>Run Pipeline Sync</span>
            </button>
            <button className="btn btn-secondary" onClick={onOpenERD}>
              <Icons.ERD />
              <span>View ERD Diagram</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Metrics */}
      <div className="metric-grid">
        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Target Tables</span>
            <div className="metric-icon-box blue"><Icons.Database /></div>
          </div>
          <div className="metric-value">{entities.length || 8}</div>
          <div className="metric-subtext">PostgreSQL schema tables</div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Total Records</span>
            <div className="metric-icon-box green"><Icons.Overview /></div>
          </div>
          <div className="metric-value">{totalRecords.toLocaleString()}</div>
          <div className="metric-subtext">Rows currently stored in DB</div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Active Connectors</span>
            <div className="metric-icon-box purple"><Icons.Connectors /></div>
          </div>
          <div className="metric-value">3</div>
          <div className="metric-subtext">Supplier, PO & Invoice modules</div>
        </div>

        <div className="metric-card">
          <div className="metric-header">
            <span className="metric-label">Last Run Status</span>
            <div className="metric-icon-box amber"><Icons.History /></div>
          </div>
          <div className="metric-value" style={{ fontSize: "19px", marginTop: "4px" }}>
            {dashboardStats?.last_run?.status || "Ready"}
          </div>
          <div className="metric-subtext">
            {dashboardStats?.last_run?.started_at
              ? formatDate(dashboardStats.last_run.started_at)
              : "Awaiting initial sync"}
          </div>
        </div>
      </div>

      {/* Entity Catalog Grid */}
      <div className="card-section">
        <div className="card-section-header">
          <div>
            <h3 className="card-section-title">Database Entities Catalog</h3>
            <p className="card-section-subtitle">
              8 integration tables populated by SAP S/4HANA OData collections.
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <button className="btn btn-secondary btn-sm" onClick={onOpenERD}>
              <Icons.ERD />
              <span>View ERD Diagram</span>
            </button>
            <button className="btn btn-secondary btn-sm" onClick={onRefresh}>
              <Icons.Refresh />
              <span>Refresh Counts</span>
            </button>
          </div>
        </div>

        {loadingEntities ? (
          <div className="empty-box">
            <div className="spinner" />
            <span>Loading catalog entities...</span>
          </div>
        ) : (
          <div className="entity-catalog-grid">
            {entities.map((item) => (
              <div
                key={item.name}
                className="entity-card-item"
                onClick={() => {
                  onSelectEntity(item.name);
                  onNavigate("explore");
                }}
              >
                <div>
                  <div className="entity-card-top">
                    <span className="entity-card-name">{item.label}</span>
                    <span className="record-badge">{item.record_count} rows</span>
                  </div>
                  <div className="entity-card-table">{item.name}</div>
                  <p className="entity-card-desc">{item.description || "Master entity table."}</p>
                </div>
                <div className="entity-card-footer">
                  <span className="card-action-link">
                    <span>Inspect Schema</span>
                    <Icons.ArrowRight />
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
