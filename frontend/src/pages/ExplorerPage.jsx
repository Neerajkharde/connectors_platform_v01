import { useState } from "react";
import { Icons } from "../components/Icons";
import { formatReference, formatCellValue } from "../utils/formatters";

export function ExplorerPage({
  entities,
  selectedEntity,
  onSelectEntity,
  fields,
  records,
  loadingDetails,
  limit,
  onChangeLimit,
  onRefreshDetails,
  onNavigateExtraction,
  onOpenERD,
}) {
  const [search, setSearch] = useState("");
  const [fieldSearch, setFieldSearch] = useState("");
  const [subTab, setSubTab] = useState("schema"); // "schema" | "preview"

  const filteredEntities = entities.filter(
    (e) =>
      e.label.toLowerCase().includes(search.toLowerCase()) ||
      e.name.toLowerCase().includes(search.toLowerCase())
  );

  const filteredFields = fields.filter(
    (f) =>
      f.name.toLowerCase().includes(fieldSearch.toLowerCase()) ||
      (f.description && f.description.toLowerCase().includes(fieldSearch.toLowerCase()))
  );

  const selectedEntityObj = entities.find((e) => e.name === selectedEntity);

  return (
    <div className="explorer-container">
      {/* Left Selector Sidebar */}
      <div className="explorer-sidebar">
        <div className="explorer-sidebar-header">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
            <span style={{ fontSize: "12px", fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Entities ({entities.length})
            </span>
            <button
              className="btn btn-secondary btn-sm"
              onClick={onOpenERD}
              title="View Entity-Relationship Diagram"
              style={{ padding: "4px 8px", fontSize: "11px" }}
            >
              <Icons.ERD />
              <span>ERD</span>
            </button>
          </div>

          <div className="search-input-wrapper">
            <span className="search-icon-svg"><Icons.Search /></span>
            <input
              className="search-box"
              type="text"
              placeholder="Filter entities..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        <div className="entity-nav-list">
          {filteredEntities.map((ent) => (
            <button
              key={ent.name}
              className={`entity-nav-item ${selectedEntity === ent.name ? "active" : ""}`}
              onClick={() => onSelectEntity(ent.name)}
            >
              <span>{ent.label}</span>
              <span className="record-badge">{ent.record_count}</span>
            </button>
          ))}
          {filteredEntities.length === 0 && (
            <div style={{ padding: "16px", textAlign: "center", color: "#94a3b8", fontSize: "12px" }}>
              No matching tables.
            </div>
          )}
        </div>
      </div>

      {/* Main Details Panel */}
      <div className="explorer-main">
        {!selectedEntity ? (
          <div className="empty-box">
            <div className="empty-icon"><Icons.Database /></div>
            <h3 style={{ fontSize: "16px", color: "#0f172a" }}>Select a Database Entity</h3>
            <p>Select any table from the left sidebar to inspect columns, constraints, and live data records.</p>
            <div style={{ marginTop: "12px" }}>
              <button className="btn btn-secondary btn-sm" onClick={onOpenERD}>
                <Icons.ERD />
                <span>View Full ERD Diagram</span>
              </button>
            </div>
          </div>
        ) : (
          <div>
            {/* Entity Header */}
            <div className="entity-detail-header">
              <div>
                <h2 className="entity-main-title">{selectedEntityObj?.label || selectedEntity}</h2>
                <div className="entity-meta-row">
                  <span>PostgreSQL Table: <code>{selectedEntity}</code></span>
                  <span>•</span>
                  <span className="tag-badge blue">{fields.length} Columns</span>
                  <span className="tag-badge purple">{records.length} Preview Records</span>
                </div>
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={onOpenERD}
                  title="View Full ERD"
                >
                  <Icons.ERD />
                  <span>ERD</span>
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={onRefreshDetails}
                  disabled={loadingDetails}
                >
                  <Icons.Refresh />
                  <span>Reload</span>
                </button>
              </div>
            </div>

            {/* Sub-tabs: Schema vs Preview */}
            <div className="subnav-tabs">
              <button
                className={`subnav-tab-btn ${subTab === "schema" ? "active" : ""}`}
                onClick={() => setSubTab("schema")}
              >
                <span>Schema & Relationships</span>
              </button>
              <button
                className={`subnav-tab-btn ${subTab === "preview" ? "active" : ""}`}
                onClick={() => setSubTab("preview")}
              >
                <span>Data Preview ({records.length})</span>
              </button>
            </div>

            {loadingDetails ? (
              <div className="empty-box">
                <div className="spinner" />
                <span>Loading entity schema and preview records...</span>
              </div>
            ) : (
              <>
                {/* 1. Schema View */}
                {subTab === "schema" && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                      <div className="search-input-wrapper" style={{ width: "260px" }}>
                        <span className="search-icon-svg"><Icons.Search /></span>
                        <input
                          className="search-box"
                          type="text"
                          placeholder="Filter columns..."
                          value={fieldSearch}
                          onChange={(e) => setFieldSearch(e.target.value)}
                        />
                      </div>

                      <div style={{ fontSize: "12px", color: "#64748b", display: "flex", gap: "10px" }}>
                        <span><span className="pill-key pk">PK</span> Primary Key</span>
                        <span><span className="pill-key fk">FK</span> Foreign Key</span>
                      </div>
                    </div>

                    <div className="table-wrapper">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Column</th>
                            <th>Data Type</th>
                            <th>Nullable</th>
                            <th>Key</th>
                            <th>Reference</th>
                            <th>Description</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredFields.map((f) => (
                            <tr key={f.name}>
                              <td><strong>{f.name}</strong></td>
                              <td><span className="pill-type">{f.type}</span></td>
                              <td>{f.nullable ? "YES" : "NO"}</td>
                              <td>
                                {f.primary_key ? (
                                  <span className="pill-key pk">PK</span>
                                ) : f.foreign_key ? (
                                  <span className="pill-key fk">FK</span>
                                ) : (
                                  "—"
                                )}
                              </td>
                              <td>
                                {f.foreign_key ? (
                                  <code>{formatReference(f.foreign_key)}</code>
                                ) : (
                                  "—"
                                )}
                              </td>
                              <td style={{ color: "#64748b", fontSize: "12px", maxWidth: "280px", whiteSpace: "normal" }}>
                                {f.description || "—"}
                              </td>
                            </tr>
                          ))}
                          {filteredFields.length === 0 && (
                            <tr>
                              <td colSpan="6" style={{ textAlign: "center", padding: "20px", color: "#94a3b8" }}>
                                No columns matched the filter.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* 2. Data Preview View */}
                {subTab === "preview" && (
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px" }}>
                      <span style={{ fontSize: "13px", color: "#64748b" }}>
                        Showing top {records.length} records from PostgreSQL
                      </span>

                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "12px", color: "#64748b" }}>Limit:</span>
                        <select
                          value={limit}
                          onChange={(e) => onChangeLimit(Number(e.target.value))}
                          style={{ padding: "4px 8px", borderRadius: "4px", border: "1px solid #cbd5e1" }}
                        >
                          <option value={10}>10</option>
                          <option value={25}>25</option>
                          <option value={50}>50</option>
                          <option value={100}>100</option>
                        </select>
                      </div>
                    </div>

                    {records.length === 0 ? (
                      <div className="empty-box">
                        <p>No records found in <code>{selectedEntity}</code>.</p>
                        <button className="btn btn-primary btn-sm" onClick={onNavigateExtraction}>
                          Run Extraction Pipeline
                        </button>
                      </div>
                    ) : (
                      <div className="table-wrapper">
                        <table className="data-table">
                          <thead>
                            <tr>
                              {fields.map((f) => (
                                <th key={f.name}>{f.name}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {records.map((r, i) => (
                              <tr key={i}>
                                {fields.map((f) => (
                                  <td key={f.name}>
                                    {r[f.name] === null || r[f.name] === undefined ? (
                                      <span style={{ color: "#cbd5e1" }}>null</span>
                                    ) : (
                                      formatCellValue(r[f.name])
                                    )}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
