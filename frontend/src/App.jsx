import { useEffect, useState } from "react";
import "./App.css";

// Services & API
import { api } from "./services/api";

// Layout & Common Components
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { Alert } from "./components/Alert";
import { ERDModal } from "./components/ERDModal";

// Modular Pages
import { OverviewPage } from "./pages/OverviewPage";
import { ExplorerPage } from "./pages/ExplorerPage";
import { ExtractionPage } from "./pages/ExtractionPage";
import { ConnectorsPage } from "./pages/ConnectorsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LineagePage } from "./pages/LineagePage";

function App() {
  // Navigation State
  const [activeTab, setActiveTab] = useState("overview");

  // Catalog & Selected Entity State
  const [entities, setEntities] = useState([]);
  const [selectedEntity, setSelectedEntity] = useState("");
  const [fields, setFields] = useState([]);
  const [records, setRecords] = useState([]);
  const [limit, setLimit] = useState(25);

  // Loading States & Refresh Trigger
  const [loadingEntities, setLoadingEntities] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // Health and System State
  const [health, setHealth] = useState({
    state: "checking", // "online" | "warning" | "offline"
    label: "Checking system...",
    data: null,
  });

  const [alert, setAlert] = useState({ type: "", message: "" });
  const [dashboardStats, setDashboardStats] = useState(null);
  const [erdModalOpen, setErdModalOpen] = useState(false);

  // Connectors State
  const [connectors, setConnectors] = useState([]);
  const [loadingConnectors, setLoadingConnectors] = useState(false);

  // History & Watermarks State
  const [runs, setRuns] = useState([]);
  const [syncState, setSyncState] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Live Extraction Trigger State
  const [extracting, setExtracting] = useState(false);
  const [extractionTask, setExtractionTask] = useState(null);

  // Check Backend and PostgreSQL Health
  async function checkHealth() {
    try {
      const data = await api.checkHealth();
      const dbConnected = data.database?.connected;
      if (dbConnected) {
        setHealth({ state: "online", label: "PostgreSQL Connected", data });
      } else {
        setHealth({ state: "warning", label: "PostgreSQL Disconnected", data });
      }
    } catch {
      setHealth({ state: "offline", label: "FastAPI Backend Offline", data: null });
    }
  }

  // Load Aggregated Dashboard Stats
  async function loadDashboardStats() {
    try {
      const stats = await api.getDashboardStats();
      setDashboardStats(stats);
    } catch {
      // Silently handled
    }
  }

  // Periodic Health Polling
  useEffect(() => {
    checkHealth();
    loadDashboardStats();
    const interval = setInterval(checkHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  // Load Entities Catalog
  useEffect(() => {
    async function loadEntities() {
      setLoadingEntities(true);
      try {
        const data = await api.getEntities();
        const list = (data.entities || []).map((e) => ({
          name: e.name || e.entity,
          label: e.label || e.name,
          record_count: e.record_count ?? 0,
          description: e.description || "",
        }));
        setEntities(list);
      } catch (err) {
        setAlert({ type: "error", message: `Could not load entities: ${err.message}` });
      } finally {
        setLoadingEntities(false);
      }
    }
    loadEntities();
  }, [refreshKey]);

  // Load Details for Selected Entity
  useEffect(() => {
    if (!selectedEntity) {
      setFields([]);
      setRecords([]);
      return;
    }

    const controller = new AbortController();

    async function loadDetails() {
      setLoadingDetails(true);
      try {
        const [fieldData, recordData] = await Promise.all([
          api.getEntityFields(selectedEntity, controller.signal),
          api.getEntityRecords(selectedEntity, limit, 0, controller.signal),
        ]);

        if (controller.signal.aborted) return;

        setFields(fieldData.fields || []);
        setRecords(recordData.records || []);
      } catch (err) {
        if (err.name === "AbortError") return;
        setAlert({ type: "error", message: `Failed loading ${selectedEntity}: ${err.message}` });
      } finally {
        if (!controller.signal.aborted) {
          setLoadingDetails(false);
        }
      }
    }

    loadDetails();
    return () => controller.abort();
  }, [selectedEntity, limit, refreshKey]);

  // Lazy Load Connectors
  useEffect(() => {
    if (activeTab === "connectors" && connectors.length === 0) {
      async function fetchConnectors() {
        setLoadingConnectors(true);
        try {
          const res = await api.getConnectors();
          setConnectors(res.connectors || []);
        } catch (err) {
          setAlert({ type: "error", message: `Failed loading connectors: ${err.message}` });
        } finally {
          setLoadingConnectors(false);
        }
      }
      fetchConnectors();
    }
  }, [activeTab]);

  // Lazy Load History & Watermarks
  useEffect(() => {
    if (activeTab === "history") {
      async function fetchHistory() {
        setLoadingHistory(true);
        try {
          const [historyRes, syncRes] = await Promise.all([
            api.getHistoryRuns(30).catch(() => ({ runs: [] })),
            api.getSyncState().catch(() => null),
          ]);
          setRuns(historyRes.runs || []);
          setSyncState(syncRes);
        } catch (err) {
          setAlert({ type: "error", message: `Failed loading history: ${err.message}` });
        } finally {
          setLoadingHistory(false);
        }
      }
      fetchHistory();
    }
  }, [activeTab, refreshKey]);

  // Trigger Live SAP Extraction
  async function handleTriggerExtraction(fullRefresh = false) {
    setAlert({ type: "", message: "" });
    setExtracting(true);
    setExtractionTask({ status: "starting", message: "Starting pipeline executor in background..." });

    try {
      const res = await api.triggerExtraction(
        ["supplier", "purchase_order", "supplier_invoice"],
        fullRefresh
      );

      const taskId = res.extraction_id;
      setExtractionTask({ status: "running", message: `Run #${taskId.slice(0, 8)} executing...` });

      const poll = setInterval(async () => {
        try {
          const statusRes = await api.getExtractionStatus(taskId);
          if (statusRes.status === "completed") {
            clearInterval(poll);
            setExtracting(false);
            setExtractionTask(null);
            setAlert({
              type: "success",
              message: "SAP S/4HANA pipeline extraction completed successfully! PostgreSQL tables updated.",
            });
            setRefreshKey((k) => k + 1);
            loadDashboardStats();
          } else if (statusRes.status === "failed") {
            clearInterval(poll);
            setExtracting(false);
            setExtractionTask(null);
            setAlert({ type: "error", message: `Extraction failed: ${statusRes.error || "Unknown pipeline error"}` });
          }
        } catch (err) {
          clearInterval(poll);
          setExtracting(false);
          setExtractionTask(null);
          setAlert({ type: "error", message: `Extraction polling error: ${err.message}` });
        }
      }, 2000);
    } catch (err) {
      setExtracting(false);
      setExtractionTask(null);
      setAlert({ type: "error", message: `Could not trigger extraction: ${err.message}` });
    }
  }

  return (
    <div className="app-shell">
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        onSelectTab={(tab) => {
          setActiveTab(tab);
          setAlert({ type: "", message: "" });
        }}
        entitiesCount={entities.length}
        health={health}
        onVerifyHealth={() => {
          checkHealth();
          loadDashboardStats();
        }}
      />

      {/* Main Content Area */}
      <div className="main-wrapper">
        <Topbar
          activeTab={activeTab}
          health={health}
          onSyncClick={() => {
            setActiveTab("extract");
            setAlert({ type: "", message: "" });
          }}
        />

        <main className="page-content">
          <Alert alert={alert} onClose={() => setAlert({ type: "", message: "" })} />

          {activeTab === "overview" && (
            <OverviewPage
              entities={entities}
              loadingEntities={loadingEntities}
              dashboardStats={dashboardStats}
              onNavigate={(tab) => {
                setActiveTab(tab);
                setAlert({ type: "", message: "" });
              }}
              onSelectEntity={(name) => setSelectedEntity(name)}
              onRefresh={() => {
                setRefreshKey((k) => k + 1);
                loadDashboardStats();
              }}
              onOpenERD={() => setErdModalOpen(true)}
            />
          )}

          {activeTab === "explore" && (
            <ExplorerPage
              entities={entities}
              selectedEntity={selectedEntity}
              onSelectEntity={(name) => setSelectedEntity(name)}
              fields={fields}
              records={records}
              loadingDetails={loadingDetails}
              limit={limit}
              onChangeLimit={(val) => setLimit(val)}
              onRefreshDetails={() => setRefreshKey((k) => k + 1)}
              onNavigateExtraction={() => {
                setActiveTab("extract");
                setAlert({ type: "", message: "" });
              }}
              onOpenERD={() => setErdModalOpen(true)}
            />
          )}

          {activeTab === "extract" && (
            <ExtractionPage
              entities={entities}
              selectedEntity={selectedEntity}
              onSelectEntity={(name) => setSelectedEntity(name)}
              fields={fields}
              records={records}
              onTriggerExtraction={handleTriggerExtraction}
              extracting={extracting}
              extractionTask={extractionTask}
              onShowAlert={(type, message) => setAlert({ type, message })}
            />
          )}

          {activeTab === "connectors" && (
            <ConnectorsPage connectors={connectors} loadingConnectors={loadingConnectors} />
          )}

          {activeTab === "history" && (
            <HistoryPage syncState={syncState} runs={runs} loadingHistory={loadingHistory} />
          )}

          {activeTab === "lineage" && <LineagePage />}
        </main>
      </div>

      {/* ERD Modal Dialog */}
      <ERDModal isOpen={erdModalOpen} onClose={() => setErdModalOpen(false)} />
    </div>
  );
}

export default App;
