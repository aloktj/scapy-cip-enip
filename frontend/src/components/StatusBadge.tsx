import type { CIPStatus } from "../api/types";
import { resolveStatusMessage } from "../statusMessages";

interface StatusBadgeProps {
  status?: CIPStatus | null;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  if (!status || (status.code == null && !status.message)) {
    return <span className="badge neutral">No status reported</span>;
  }

  const message = resolveStatusMessage(status.code, status.message ?? undefined);
  const badgeClass = status.code === 0 || status.code == null ? "success" : "error";

  return (
    <span className={`badge ${badgeClass}`}>
      <span>{status.code != null ? `0x${status.code.toString(16).padStart(2, "0")}` : "--"}</span>
      <span>{message}</span>
    </span>
  );
}
