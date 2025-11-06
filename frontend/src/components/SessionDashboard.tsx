import type { SessionDiagnosticsResponse, SessionResponse } from "../api/types";
import { StatusBadge } from "./StatusBadge";

interface SessionDashboardProps {
  session: SessionResponse | null;
  diagnostics: SessionDiagnosticsResponse | null;
  host: string;
  port: string;
  loading: boolean;
  onHostChange: (value: string) => void;
  onPortChange: (value: string) => void;
  onStart: () => void;
  onStop: () => void;
}

export function SessionDashboard({
  session,
  diagnostics,
  host,
  port,
  loading,
  onHostChange,
  onPortChange,
  onStart,
  onStop
}: SessionDashboardProps) {
  const active = Boolean(session);
  const connection = diagnostics?.connection ?? session?.connection ?? null;
  const keepAlive = diagnostics?.keep_alive_active ?? false;
  const lastActivity = diagnostics ? new Date(diagnostics.last_activity * 1000) : null;
  const endpointHost = diagnostics?.host ?? session?.host ?? null;
  const endpointPort = diagnostics?.port ?? session?.port ?? null;

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ marginBottom: 0 }}>Session Controls</h2>
        <div style={{ display: "flex", gap: "0.75rem" }}>
          <button onClick={onStart} disabled={loading || active}>
            {loading && !active ? "Starting…" : "Start session"}
          </button>
          <button onClick={onStop} disabled={loading || !active}>
            Stop session
          </button>
        </div>
      </div>
      <p style={{ marginTop: "1rem", marginBottom: "1.5rem", color: "#475569" }}>
        Manage CIP/ENIP sessions and inspect the latest PLC connection status in real time.
      </p>

      <div
        style={{
          display: "grid",
          gap: "0.75rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          marginBottom: "1.25rem"
        }}
      >
        <label style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
          <span style={{ fontWeight: 500 }}>PLC host</span>
          <input
            type="text"
            value={host}
            onChange={(event) => onHostChange(event.target.value)}
            placeholder="127.0.0.1"
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
          <span style={{ fontWeight: 500 }}>PLC port</span>
          <input
            type="number"
            min={1}
            value={port}
            onChange={(event) => onPortChange(event.target.value)}
            placeholder="44818"
          />
        </label>
      </div>

      {connection ? (
        <table className="status-table">
          <tbody>
            <tr>
              <th scope="row">Session ID</th>
              <td>{session?.session_id ?? "--"}</td>
            </tr>
            <tr>
              <th scope="row">PLC host</th>
              <td>{endpointHost ?? "--"}</td>
            </tr>
            <tr>
              <th scope="row">PLC port</th>
              <td>{endpointPort ?? "--"}</td>
            </tr>
            <tr>
              <th scope="row">ENIP connection ID</th>
              <td>{connection.enip_connection_id}</td>
            </tr>
            <tr>
              <th scope="row">Sequence counter</th>
              <td>{connection.sequence}</td>
            </tr>
            <tr>
              <th scope="row">Connected</th>
              <td>{connection.connected ? "Yes" : "No"}</td>
            </tr>
            <tr>
              <th scope="row">CIP Status</th>
              <td>
                <StatusBadge status={connection.last_status} />
              </td>
            </tr>
            {diagnostics && (
              <tr>
                <th scope="row">Keep-alive pattern</th>
                <td>
                  <code>{diagnostics.keep_alive_pattern_hex}</code>
                </td>
              </tr>
            )}
            {lastActivity && (
              <tr>
                <th scope="row">Last activity</th>
                <td>{lastActivity.toLocaleString()}</td>
              </tr>
            )}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "#475569" }}>Start a session to populate connection details.</p>
      )}

      <div className="keep-alive-indicator" style={{ marginTop: "1.25rem" }}>
        <span className={`keep-alive-dot ${keepAlive ? "active" : ""}`} />
        <span>{keepAlive ? "Keep-alive active" : "Awaiting keep-alive"}</span>
      </div>
    </div>
  );
}
