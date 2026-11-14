// API Client Service

export const API_BASE_URL = import.meta.env.VITE_API_URL !== undefined
  ? import.meta.env.VITE_API_URL
  : (typeof window !== "undefined" && window.location.port === "5173" ? "" : "http://127.0.0.1:8000");

export async function apiRequest(path, signal, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, { signal, ...options });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || data.message || `API error (${response.status})`);
  }

  return data;
}

// Named API calls
export const api = {
  checkHealth: (signal) => apiRequest("/api/health", signal),
  getDashboardStats: (signal) => apiRequest("/api/dashboard/stats", signal),
  getEntities: (signal) => apiRequest("/api/entities", signal),
  getEntityFields: (entity, signal) => apiRequest(`/api/entities/${encodeURIComponent(entity)}/fields`, signal),
  getEntityRecords: (entity, limit = 25, offset = 0, signal) =>
    apiRequest(`/api/entities/${encodeURIComponent(entity)}/records?limit=${limit}&offset=${offset}`, signal),
  getConnectors: (signal) => apiRequest("/api/connectors", signal),
  getHistoryRuns: (limit = 30, signal) => apiRequest(`/api/history/runs?limit=${limit}`, signal),
  getSyncState: (signal) => apiRequest("/api/sync-state", signal),
  triggerExtraction: (entities, fullRefresh = false) =>
    apiRequest("/api/extract", null, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entities, full_refresh: fullRefresh }),
    }),
  getExtractionStatus: (id) => apiRequest(`/api/extract/${id}`),
};
