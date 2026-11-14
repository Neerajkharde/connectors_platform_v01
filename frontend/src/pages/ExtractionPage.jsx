import { useState } from "react";
import { Icons } from "../components/Icons";
import { escapeCSV } from "../utils/formatters";

export function ExtractionPage({
  entities,
  selectedEntity,
  onSelectEntity,
  fields,
  records,
  onTriggerExtraction,
  extracting,
  extractionTask,
  onShowAlert,
}) {
  const [fullRefresh, setFullRefresh] = useState(false);
  const [selectedFields, setSelectedFields] = useState([]);
  const [fieldSearch, setFieldSearch] = useState("");

  const filteredFields = fields.filter(
    (f) =>
      f.name.toLowerCase().includes(fieldSearch.toLowerCase()) ||
      (f.description && f.description.toLowerCase().includes(fieldSearch.toLowerCase()))
  );

  function toggleField(fieldName) {
    setSelectedFields((prev) =>
      prev.includes(fieldName) ? prev.filter((n) => n !== fieldName) : [...prev, fieldName]
    );
  }

  function selectAllFields() {
    setSelectedFields(fields.map((f) => f.name));
  }

  function selectKeysOnly() {
    setSelectedFields(
      fields.filter((f) => f.primary_key || f.foreign_key).map((f) => f.name)
    );
  }

  function resetFields() {
    setSelectedFields([]);
  }

  function handleExportCSV() {
    if (!selectedEntity) {
      onShowAlert("error", "Please choose an entity first.");
      return;
    }
    if (selectedFields.length === 0) {
      onShowAlert("error", "Please select at least one field to export.");
      return;
    }

    const header = selectedFields.map(escapeCSV).join(",");
    const rows = records.map((row) =>
      selectedFields.map((f) => escapeCSV(row[f])).join(",")
    );

    const csvContent = "\uFEFF" + [header, ...rows].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedEntity}_export.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    onShowAlert("success", `${records.length} records exported to ${selectedEntity}_export.csv`);
  }

  return (
    <div>
      {/* Live SAP Pipeline Runner */}
      <div className="sync-panel-card">
        <div className="sync-panel-header">
          <div>
            <h3 className="card-section-title">SAP S/4HANA Extraction Pipeline</h3>
            <p className="card-section-subtitle">
              Executes the three-stage extraction workflow (Suppliers &rarr; Purchase Orders &rarr; Invoices) with checkpoint commits.
            </p>
          </div>
        </div>

        <div className="sync-actions-row">
          <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={fullRefresh}
              onChange={(e) => setFullRefresh(e.target.checked)}
              style={{ accentColor: "#0284c7" }}
            />
            <span>Full Refresh (ignore saved incremental watermarks)</span>
          </label>

          <div style={{ marginLeft: "auto", display: "flex", gap: "10px" }}>
            <button
              className="btn btn-primary"
              onClick={() => onTriggerExtraction(fullRefresh)}
              disabled={extracting}
            >
              {extracting ? <div className="spinner" /> : <Icons.Extract />}
              <span>{extracting ? "Extraction in Progress..." : "Trigger Live Sync"}</span>
            </button>
          </div>
        </div>

        {extractionTask && (
          <div className="progress-banner">
            <div className="spinner" />
            <span>{extractionTask.message}</span>
          </div>
        )}
      </div>

      {/* Ad-Hoc Column Selection & CSV Export */}
      <div className="card-section">
        <div className="card-section-header">
          <div>
            <h3 className="card-section-title">Column Selection & CSV Export</h3>
            <p className="card-section-subtitle">
              Select specific entity fields to preview and download as CSV.
            </p>
          </div>

          <div style={{ display: "flex", gap: "8px" }}>
            <select
              value={selectedEntity}
              onChange={(e) => {
                onSelectEntity(e.target.value);
                setSelectedFields([]);
              }}
              style={{ padding: "6px 12px", borderRadius: "6px", border: "1px solid #cbd5e1" }}
            >
              <option value="">-- Choose Entity --</option>
              {entities.map((e) => (
                <option key={e.name} value={e.name}>
                  {e.label} ({e.name})
                </option>
              ))}
            </select>

            <button
              className="btn btn-primary btn-sm"
              onClick={handleExportCSV}
              disabled={!selectedEntity || selectedFields.length === 0}
            >
              <Icons.Extract />
              <span>Download CSV</span>
            </button>
          </div>
        </div>

        {!selectedEntity ? (
          <div className="empty-box">
            <p>Please select an entity from the dropdown above to choose columns for export.</p>
          </div>
        ) : (
          <div style={{ padding: "20px 24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px", flexWrap: "wrap", gap: "8px" }}>
              <div className="search-input-wrapper" style={{ width: "240px" }}>
                <span className="search-icon-svg"><Icons.Search /></span>
                <input
                  className="search-box"
                  type="text"
                  placeholder="Search fields..."
                  value={fieldSearch}
                  onChange={(e) => setFieldSearch(e.target.value)}
                />
              </div>

              <div style={{ display: "flex", gap: "8px" }}>
                <button className="btn btn-secondary btn-sm" onClick={selectAllFields}>
                  Select All
                </button>
                <button className="btn btn-secondary btn-sm" onClick={selectKeysOnly}>
                  Keys Only
                </button>
                <button className="btn btn-secondary btn-sm" onClick={resetFields}>
                  Deselect All
                </button>
              </div>
            </div>

            <div className="field-grid-list">
              {filteredFields.map((f) => (
                <label key={f.name} className="field-checkbox-item">
                  <input
                    type="checkbox"
                    checked={selectedFields.includes(f.name)}
                    onChange={() => toggleField(f.name)}
                  />
                  <span style={{ fontWeight: 500 }}>{f.name}</span>
                  {f.primary_key && <span className="pill-key pk" style={{ marginLeft: "auto" }}>PK</span>}
                  {!f.primary_key && f.foreign_key && <span className="pill-key fk" style={{ marginLeft: "auto" }}>FK</span>}
                </label>
              ))}
            </div>

            <div style={{ fontSize: "12px", color: "#64748b", marginBottom: "16px" }}>
              Selected <strong>{selectedFields.length}</strong> of <strong>{fields.length}</strong> columns
            </div>

            {/* Data Preview */}
            <div className="card-section-title" style={{ fontSize: "14px", marginBottom: "8px" }}>
              Export Data Preview ({records.length} records)
            </div>
            {records.length === 0 ? (
              <div className="empty-box" style={{ padding: "24px" }}>
                No records stored in this table. You can still export empty column headers.
              </div>
            ) : (
              <div className="table-wrapper">
                <table className="data-table">
                  <thead>
                    <tr>
                      {selectedFields.map((f) => (
                        <th key={f}>{f}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {records.slice(0, 10).map((r, i) => (
                      <tr key={i}>
                        {selectedFields.map((f) => (
                          <td key={f}>
                            {r[f] === null || r[f] === undefined ? "—" : String(r[f])}
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
      </div>
    </div>
  );
}
