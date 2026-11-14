// Data formatting helpers

export function formatDate(isoStr) {
  if (!isoStr) return "—";
  try {
    const d = new Date(isoStr);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return isoStr;
  }
}

export function formatReference(foreignKey) {
  if (!foreignKey) return "—";
  if (typeof foreignKey === "object") {
    return `${foreignKey.referenced_table}.${foreignKey.referenced_column}`;
  }
  return String(foreignKey);
}

export function formatCellValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function escapeCSV(val) {
  if (val === null || val === undefined) return '""';
  const text = typeof val === "object" ? JSON.stringify(val) : String(val);
  return `"${text.replace(/"/g, '""')}"`;
}
