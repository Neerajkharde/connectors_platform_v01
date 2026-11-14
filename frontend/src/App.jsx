
import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

function App() {
  const [entities, setEntities] = useState([]);
  const [selectedEntity, setSelectedEntity] = useState("");
  const [fields, setFields] = useState([]);
  const [records, setRecords] = useState([]);
  const [selectedFields, setSelectedFields] = useState([]);

  const [search, setSearch] = useState("");
  const [fieldSearch, setFieldSearch] = useState("");
  const [limit, setLimit] = useState(10);
  const [activeTab, setActiveTab] = useState("explore");

  const [loadingEntities, setLoadingEntities] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const [connection, setConnection] = useState("Checking...");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // API request helper
  async function apiRequest(path, signal) {
    const response = await fetch(`${API}${path}`, { signal });
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        data.detail || data.message || `API error: ${response.status}`
      );
    }

    return data;
  }

  // Format foreign key references
  function formatReference(foreignKey) {
    if (!foreignKey) return "—";

    if (typeof foreignKey === "object") {
      return `${foreignKey.referenced_table}.${foreignKey.referenced_column}`;
    }

    return String(foreignKey);
  }

  // Check database connection
  useEffect(() => {
    async function checkConnection() {
      try {
        await apiRequest("/api/health");
        setConnection("PostgreSQL Connected");
      } catch {
        setConnection("PostgreSQL Disconnected");
      }
    }

    checkConnection();
  }, []);

  // Load entities
  useEffect(() => {
    async function loadEntities() {
      setLoadingEntities(true);
      setError("");

      try {
        const data = await apiRequest("/api/entities");

        const entityList = (data.entities || [])
          .map((item) => ({
            name: item.name || item.entity,
            label: item.label || item.name || item.entity,
          }))
          .filter((item) => item.name);

        setEntities(entityList);
      } catch (err) {
        setError(`Unable to load entities: ${err.message}`);
      } finally {
        setLoadingEntities(false);
      }
    }

    loadEntities();
  }, []);

  // Load fields and records whenever entity, limit or refresh changes
  useEffect(() => {
    if (!selectedEntity) {
      setFields([]);
      setRecords([]);
      setSelectedFields([]);
      return;
    }

    const controller = new AbortController();

    async function loadEntityDetails() {
      setLoadingDetails(true);
      setError("");
      setSuccess("");

      try {
        const entity = encodeURIComponent(selectedEntity);

        const [fieldData, recordData] = await Promise.all([
          apiRequest(
            `/api/entities/${entity}/fields`,
            controller.signal
          ),
          apiRequest(
            `/api/entities/${entity}/records?limit=${limit}`,
            controller.signal
          ),
        ]);

        if (controller.signal.aborted) return;

        const loadedFields = fieldData.fields || [];
        const loadedRecords = recordData.records || [];

        setFields(loadedFields);
        setRecords(loadedRecords);

        // Primary keys and foreign keys selected by default
        const defaultFields = loadedFields
          .filter((field) => field.primary_key || field.foreign_key)
          .map((field) => field.name);

        setSelectedFields(defaultFields);
      } catch (err) {
        if (err.name === "AbortError") return;

        setError(`Unable to load ${selectedEntity}: ${err.message}`);
      } finally {
        if (!controller.signal.aborted) {
          setLoadingDetails(false);
        }
      }
    }

    loadEntityDetails();

    return () => controller.abort();
  }, [selectedEntity, limit, refreshKey]);

  // Search entities
  const filteredEntities = useMemo(() => {
    return entities.filter((entity) =>
      entity.label.toLowerCase().includes(search.toLowerCase())
    );
  }, [entities, search]);

  // Search fields
  const filteredFields = useMemo(() => {
    return fields.filter((field) =>
      field.name.toLowerCase().includes(fieldSearch.toLowerCase())
    );
  }, [fields, fieldSearch]);

  // Selected entity information
  const selectedEntityInfo = entities.find(
    (entity) => entity.name === selectedEntity
  );

  // Select an entity
  function handleEntitySelect(entityName) {
    setSelectedEntity(entityName);
    setActiveTab("explore");
    setFieldSearch("");
    setError("");
    setSuccess("");
  }

  // Select or deselect fields
  function toggleField(field) {
    if (field.primary_key) return;

    setSelectedFields((previous) =>
      previous.includes(field.name)
        ? previous.filter((name) => name !== field.name)
        : [...previous, field.name]
    );

    setSuccess("");
  }

  // Select all fields
  function selectAllFields() {
    setSelectedFields(fields.map((field) => field.name));
    setSuccess("");
  }

  // Reset selection to primary and foreign keys
  function resetFields() {
    setSelectedFields(
      fields
        .filter((field) => field.primary_key || field.foreign_key)
        .map((field) => field.name)
    );

    setSuccess("");
  }

  // Refresh records
  function refreshPreview() {
    setError("");
    setSuccess("");
    setRefreshKey((previous) => previous + 1);
  }

  // Download selected data as CSV
  function downloadCSV() {
    setError("");
    setSuccess("");

    if (!selectedEntity) {
      setError("Please select an entity first.");
      return;
    }

    if (selectedFields.length === 0) {
      setError("Please select at least one field.");
      return;
    }

    function escapeCSV(value) {
      if (value === null || value === undefined) return '""';

      const text =
        typeof value === "object"
          ? JSON.stringify(value)
          : String(value);

      return `"${text.replace(/"/g, '""')}"`;
    }

    const header = selectedFields.map(escapeCSV).join(",");

    const rows = records.map((record) =>
      selectedFields
        .map((field) => escapeCSV(record[field]))
        .join(",")
    );

    const csv = "\uFEFF" + [header, ...rows].join("\r\n");

    const blob = new Blob([csv], {
      type: "text/csv;charset=utf-8;",
    });

    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${selectedEntity}_data.csv`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(url);

    if (records.length === 0) {
      setSuccess(
        "CSV downloaded with column headers only. No records were available."
      );
    } else {
      setSuccess(
        `${records.length} records downloaded successfully.`
      );
    }
  }

  // Format record values
  function formatValue(value) {
    if (value === null || value === undefined) return "—";

    if (typeof value === "object") {
      return JSON.stringify(value);
    }

    return String(value);
  }

  const disconnected = connection.includes("Disconnected");

  return (
    <div className="app">
      {/* SIDEBAR */}
      <aside className="sidebar">
        <h2>DataBridge</h2>

        <p className="sidebar-heading">WORKSPACE</p>

        <button
          className={`nav-item ${
            activeTab === "explore" ? "active" : ""
          }`}
          onClick={() => setActiveTab("explore")}
        >
          ◈ Explore Data
        </button>

        <button
          className={`nav-item ${
            activeTab === "extract" ? "active" : ""
          }`}
          onClick={() => setActiveTab("extract")}
        >
          ⇩ Select & Extract
        </button>

        <p className="sidebar-heading">CONNECTION</p>

        <div className="connection-item">● PostgreSQL</div>
        <div className="connection-item">● SAP S/4HANA</div>

        <div className="sidebar-bottom">
          <div className="integration-name">
            SAP Data Integration
          </div>

          <div className="connection-status">
            <span
              className={`status-dot ${
                disconnected ? "disconnected" : ""
              }`}
            />
            {connection}
          </div>
        </div>
      </aside>

      {/* MAIN CONTENT */}
      <main className="main">
        <header className="topbar">
          <strong>Data Integration Workspace</strong>

          <div className="connection">
            <span
              className={`status-dot ${
                disconnected ? "disconnected" : ""
              }`}
            />
            {connection}
          </div>
        </header>

        <div className="content">
          {/* PAGE HEADING */}
          <div className="page-heading">
            <h1>Data Explorer</h1>

            <p>
              Explore database entities, understand their structure
              and select the data you want to extract.
            </p>
          </div>

          {/* TABS */}
          <div className="tabs">
            <button
              className={`tab ${
                activeTab === "explore" ? "active-tab" : ""
              }`}
              onClick={() => setActiveTab("explore")}
            >
              Explore Entities
            </button>

            <button
              className={`tab ${
                activeTab === "extract" ? "active-tab" : ""
              }`}
              onClick={() => setActiveTab("extract")}
            >
              Select & Extract
            </button>
          </div>

          {/* ERROR AND SUCCESS MESSAGES */}
          {error && (
            <div className="error-message">{error}</div>
          )}

          {success && (
            <div className="success-message">{success}</div>
          )}

          <div className="entity-layout">
            {/* ENTITY LIST */}
            <section className="entity-sidebar">
              <h3>Entities</h3>

              <input
                className="search-input"
                type="text"
                placeholder="Search entities..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />

              <div className="entity-list">
                {loadingEntities ? (
                  <p>Loading entities...</p>
                ) : filteredEntities.length === 0 ? (
                  <p className="no-results">
                    No entities found.
                  </p>
                ) : (
                  filteredEntities.map((entity) => (
                    <button
                      type="button"
                      key={entity.name}
                      className={`entity-item ${
                        selectedEntity === entity.name
                          ? "selected"
                          : ""
                      }`}
                      onClick={() =>
                        handleEntitySelect(entity.name)
                      }
                    >
                      <span>{entity.label}</span>
                      <span>›</span>
                    </button>
                  ))
                )}
              </div>

              <p className="entity-count">
                {entities.length} entities available
              </p>
            </section>

            {/* ENTITY DETAILS */}
            <section className="entity-details">
              {!selectedEntity ? (
                <div className="empty-state">
                  <h2>Select an entity</h2>
                  <p>
                    Choose an entity from the left panel to explore
                    its fields and records.
                  </p>
                </div>
              ) : (
                <>
                  {/* ENTITY HEADER */}
                  <div className="entity-header">
                    <div>
                      <h2>
                        {selectedEntityInfo?.label || selectedEntity}
                      </h2>

                      <p>
                        Database table: {selectedEntity}
                      </p>
                    </div>

                    <span className="status-badge">
                      PostgreSQL Table
                    </span>
                  </div>

                  {/* STATISTICS */}
                  <div className="entity-stats">
                    <div className="stat-card">
                      <span>Total Fields</span>
                      <strong>{fields.length}</strong>
                    </div>

                    <div className="stat-card">
                      <span>Selected Fields</span>
                      <strong>{selectedFields.length}</strong>
                    </div>

                    <div className="stat-card">
                      <span>Preview Records</span>
                      <strong>{records.length}</strong>
                    </div>
                  </div>

                  {loadingDetails ? (
                    <div className="empty-state">
                      Loading entity details...
                    </div>
                  ) : (
                    <>
                      {/* EXPLORE TAB */}
                      {activeTab === "explore" && (
                        <>
                          <div className="section-heading">
                            <h3>Entity Structure</h3>
                            <p>
                              Columns, data types and key relationships.
                            </p>
                          </div>

                          <div className="key-info">
                            <span className="key-badge">PK</span>
                            Primary Key

                            <span className="key-badge fk-badge">
                              FK
                            </span>
                            Foreign Key

                            <span className="key-badge normal-badge">
                              NULL
                            </span>
                            Nullable field
                          </div>

                          <div className="table-container">
                            <table>
                              <thead>
                                <tr>
                                  <th>Column Name</th>
                                  <th>Data Type</th>
                                  <th>Nullable</th>
                                  <th>Key</th>
                                  <th>Reference</th>
                                </tr>
                              </thead>

                              <tbody>
                                {fields.map((field) => (
                                  <tr key={field.name}>
                                    <td>{field.name}</td>
                                    <td>{field.type}</td>
                                    <td>
                                      {field.nullable ? "Yes" : "No"}
                                    </td>

                                    <td>
                                      {field.primary_key ? (
                                        <span className="key-badge">
                                          PK
                                        </span>
                                      ) : field.foreign_key ? (
                                        <span className="key-badge fk-badge">
                                          FK
                                        </span>
                                      ) : (
                                        "—"
                                      )}
                                    </td>

                                    <td>
                                      {formatReference(field.foreign_key)}
                                    </td>
                                  </tr>
                                ))}

                                {fields.length === 0 && (
                                  <tr>
                                    <td colSpan="5">
                                      No columns returned by the API.
                                    </td>
                                  </tr>
                                )}
                              </tbody>
                            </table>
                          </div>

                          {/* DATA PREVIEW */}
                          <div className="preview-panel">
                            <div className="section-heading">
                              <h3>Data Preview</h3>
                              <p>
                                Sample records from {selectedEntity}.
                              </p>
                            </div>

                            <div className="field-actions">
                              <button
                                type="button"
                                onClick={refreshPreview}
                                disabled={loadingDetails}
                              >
                                ↻ Refresh Preview
                              </button>
                            </div>

                            <p className="selected-count">
                              Showing {records.length} of up to {limit} records
                            </p>

                            {records.length === 0 ? (
                              <div className="empty-state">
                                No records found in this table.
                              </div>
                            ) : (
                              <div className="table-container">
                                <table>
                                  <thead>
                                    <tr>
                                      {fields.map((field) => (
                                        <th key={field.name}>
                                          {field.name}
                                        </th>
                                      ))}
                                    </tr>
                                  </thead>

                                  <tbody>
                                    {records.map((record, index) => (
                                      <tr key={index}>
                                        {fields.map((field) => (
                                          <td key={field.name}>
                                            {formatValue(record[field.name])}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        </>
                      )}

                      {/* SELECT & EXTRACT TAB */}
                      {activeTab === "extract" && (
                        <>
                          <div className="section-heading">
                            <h3>Select Fields</h3>
                            <p>
                              Choose the columns you want to extract.
                            </p>
                          </div>

                          <input
                            className="search-input"
                            type="text"
                            placeholder="Search fields..."
                            value={fieldSearch}
                            onChange={(e) =>
                              setFieldSearch(e.target.value)
                            }
                          />

                          <div className="field-actions">
                            <button
                              type="button"
                              onClick={selectAllFields}
                            >
                              Select All
                            </button>

                            <button
                              type="button"
                              onClick={resetFields}
                            >
                              Reset Selection
                            </button>
                          </div>

                          <div className="field-list">
                            {filteredFields.map((field) => (
                              <label
                                className="field-option"
                                key={field.name}
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedFields.includes(field.name)}
                                  disabled={field.primary_key}
                                  onChange={() => toggleField(field)}
                                />

                                <span>{field.name}</span>

                                {field.primary_key && (
                                  <span className="key-badge">
                                    PK · Required
                                  </span>
                                )}

                                {!field.primary_key &&
                                  field.foreign_key && (
                                    <span className="key-badge fk-badge">
                                      FK
                                    </span>
                                  )}
                              </label>
                            ))}

                            {filteredFields.length === 0 && (
                              <p className="no-results">
                                No matching fields.
                              </p>
                            )}
                          </div>

                          <p className="selected-count">
                            {selectedFields.length} of {fields.length} fields selected
                          </p>

                          <label className="field-label">
                            Number of records to preview
                          </label>

                          <input
                            className="limit-input"
                            type="number"
                            min="1"
                            max="500"
                            value={limit}
                            onChange={(e) => {
                              const value = Number(e.target.value);

                              setLimit(
                                Math.max(1, Math.min(500, value || 1))
                              );
                            }}
                          />

                          <button
                            className="extract-button"
                            type="button"
                            onClick={downloadCSV}
                            disabled={
                              selectedFields.length === 0 ||
                              loadingDetails
                            }
                          >
                            ⇩ Download Selected Data
                          </button>

                          {/* SELECTED DATA PREVIEW */}
                          <div className="preview-panel">
                            <h3>Selected Data Preview</h3>

                            <p>
                              Preview of the fields you have selected.
                            </p>

                            {selectedFields.length === 0 ? (
                              <div className="empty-state">
                                Please select at least one field.
                              </div>
                            ) : (
                              <>
                                {records.length === 0 ? (
                                  <div className="empty-state">
                                    No records available. You can still
                                    download the CSV column headers.
                                  </div>
                                ) : (
                                  <div className="table-container">
                                    <table>
                                      <thead>
                                        <tr>
                                          {selectedFields.map((field) => (
                                            <th key={field}>{field}</th>
                                          ))}
                                        </tr>
                                      </thead>

                                      <tbody>
                                        {records.map((record, index) => (
                                          <tr key={index}>
                                            {selectedFields.map((field) => (
                                              <td key={field}>
                                                {formatValue(record[field])}
                                              </td>
                                            ))}
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        </>
                      )}
                    </>
                  )}
                </>
              )}
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
