export function Alert({ alert, onClose }) {
  if (!alert || !alert.message) return null;

  return (
    <div className={`alert ${alert.type === "error" ? "alert-error" : "alert-success"}`}>
      <span>{alert.message}</span>
      <button className="alert-close-btn" onClick={onClose}>
        &times;
      </button>
    </div>
  );
}
