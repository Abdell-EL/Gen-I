const statusLabels: Record<string, string> = {
  healthy: "Opérationnel",
  degraded: "Dégradé",
  unhealthy: "Indisponible",
  unknown: "Inconnu",
};

export function StatusBadge({ status = "unknown" }: { status?: string }) {
  const normalizedStatus = statusLabels[status] ? status : "unknown";
  return (
    <span className={`status-badge status-${normalizedStatus}`}>
      <span aria-hidden="true" className="status-dot" />
      {statusLabels[normalizedStatus]}
    </span>
  );
}
