import { formatDate } from "../utils/formatters";

export function HistoryPage({ syncState, runs, loadingHistory }) {
  return (
    <div>
      {/* Incremental Sync Watermarks */}
      <div className="card-section">
        <div className="card-section-header">
          <div>
            <h3 className="card-section-title">Saved Watermarks & Keyset Cursors</h3>
            <p className="card-section-subtitle">
              State maintained in <code>sync_state</code> table to drive incremental delta extraction.
            </p>
          </div>
        </div>

        {syncState?.watermarks && syncState.watermarks.length > 0 ? (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Entity</th>
                  <th>Watermark Column</th>
                  <th>Saved Timestamp / Key</th>
                  <th>Last Run ID</th>
                  <th>Updated At</th>
                </tr>
              </thead>
              <tbody>
                {syncState.watermarks.map((w) => (
                  <tr key={w.entity}>
                    <td><strong>{w.entity}</strong></td>
                    <td><code>{w.watermark_field}</code></td>
                    <td><span className="pill-type">{w.last_value || "—"}</span></td>
                    <td><code>{w.last_run_id ? w.last_run_id.slice(0, 8) : "—"}</code></td>
                    <td>{formatDate(w.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-box">
            <p>No watermarks saved yet. Run the extraction pipeline to establish initial watermarks.</p>
          </div>
        )}
      </div>

      {/* Execution Audit Log */}
      <div className="card-section">
        <div className="card-section-header">
          <div>
            <h3 className="card-section-title">Execution Audit Runs</h3>
            <p className="card-section-subtitle">
              Audit history of runs recorded in <code>run_log</code>.
            </p>
          </div>
        </div>

        {loadingHistory ? (
          <div className="empty-box">
            <div className="spinner" />
            <span>Loading run logs...</span>
          </div>
        ) : runs.length === 0 ? (
          <div className="empty-box">
            <p>No past execution logs found.</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Mode</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th>SAP Calls</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id}>
                    <td><code>{r.run_id.slice(0, 8)}</code></td>
                    <td><span className="tag-badge blue">{r.mode}</span></td>
                    <td>{formatDate(r.started_at)}</td>
                    <td>{formatDate(r.finished_at)}</td>
                    <td>{r.sap_calls ?? "—"}</td>
                    <td>
                      <span
                        className="tag-badge"
                        style={{
                          background: r.status === "SUCCESS" ? "#dcfce7" : r.status === "QUOTA" ? "#fef3c7" : "#fee2e2",
                          color: r.status === "SUCCESS" ? "#166534" : r.status === "QUOTA" ? "#b45309" : "#991b1b",
                        }}
                      >
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
