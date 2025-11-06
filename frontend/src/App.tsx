import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  AssemblyQueryParams,
  AssemblyReadResponse,
  AssemblyWritePayload,
  SessionDiagnosticsResponse,
  SessionResponse
} from "./api/types";
import { api, ApiError } from "./api/client";
import { SessionDashboard } from "./components/SessionDashboard";
import { AssemblyEditor } from "./components/AssemblyEditor";
import { StatusBadge } from "./components/StatusBadge";
import { resolveStatusMessage } from "./statusMessages";
import "./App.css";

const DIAGNOSTICS_INTERVAL_MS = 4000;

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export default function App() {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<SessionDiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);

  const activeStatus = useMemo(() => diagnostics?.connection.last_status ?? session?.connection.last_status, [
    diagnostics,
    session
  ]);

  useEffect(() => {
    if (!session) {
      return;
    }

    let cancelled = false;
    let timer: number | null = null;

    const pollDiagnostics = async () => {
      try {
        const report = await api.getDiagnostics(session.session_id);
        if (cancelled) {
          return;
        }
        setDiagnostics(report);
        setSession((previous) => (previous ? { ...previous, connection: report.connection } : previous));
        setDiagnosticError(null);
      } catch (error) {
        if (cancelled) {
          return;
        }
        const message = formatError(error);
        setDiagnosticError(message);
        if (error instanceof ApiError && error.status === 404) {
          setSession(null);
          setDiagnostics(null);
        }
      }
    };

    pollDiagnostics();
    timer = window.setInterval(pollDiagnostics, DIAGNOSTICS_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timer) {
        window.clearInterval(timer);
      }
    };
  }, [session?.session_id]);

  const handleStart = useCallback(async () => {
    setLoading(true);
    setGlobalError(null);
    setDiagnostics(null);
    try {
      const newSession = await api.startSession();
      setSession(newSession);
    } catch (error) {
      setGlobalError(formatError(error));
    } finally {
      setLoading(false);
    }
  }, []);

  const handleStop = useCallback(async () => {
    if (!session) {
      return;
    }
    setLoading(true);
    setGlobalError(null);
    try {
      const stopped = await api.stopSession(session.session_id);
      setSession(stopped);
      setDiagnostics(null);
    } catch (error) {
      setGlobalError(formatError(error));
    } finally {
      setLoading(false);
    }
  }, [session]);

  const handleRead = useCallback(
    async (params: AssemblyQueryParams): Promise<AssemblyReadResponse> => {
      if (!session) {
        throw new Error("Start a session before reading assemblies");
      }
      return api.readAssembly(session.session_id, params);
    },
    [session]
  );

  const handleWrite = useCallback(
    async (path: string, payload: AssemblyWritePayload): Promise<void> => {
      if (!session) {
        throw new Error("Start a session before writing assemblies");
      }
      await api.writeAssembly(session.session_id, path, payload);
    },
    [session]
  );

  const statusSummary = useMemo(() => {
    if (!activeStatus) {
      return "No CIP status received yet.";
    }
    const friendly = resolveStatusMessage(activeStatus.code, activeStatus.message ?? undefined);
    const code = activeStatus.code != null ? `0x${activeStatus.code.toString(16).padStart(2, "0")}` : "--";
    return `${code} – ${friendly}`;
  }, [activeStatus]);

  return (
    <div className="app-shell">
      <h1>CIP/ENIP Control Center</h1>

      {globalError && (
        <div className="card" style={{ borderLeft: "4px solid #ef4444", color: "#b91c1c" }}>
          <strong>Request failed:</strong> {globalError}
        </div>
      )}

      <div className="dashboard-grid">
        <SessionDashboard
          session={session}
          diagnostics={diagnostics}
          loading={loading}
          onStart={() => {
            void handleStart();
          }}
          onStop={() => {
            void handleStop();
          }}
        />

        <div className="card">
          <h2>Live CIP status</h2>
          <p style={{ color: "#475569" }}>
            Responses are decoded locally using the CIP error table so technicians see the same
            terminology as PLC operators.
          </p>
          <StatusBadge status={activeStatus ?? undefined} />
          <p style={{ marginTop: "1rem", fontSize: "0.95rem", color: "#1f2937" }}>{statusSummary}</p>
          {diagnosticError && (
            <p className="error-text" style={{ marginTop: "0.75rem" }}>
              Diagnostics stream interrupted: {diagnosticError}
            </p>
          )}
        </div>
      </div>

      <AssemblyEditor disabled={!session || loading} onRead={handleRead} onWrite={handleWrite} />
    </div>
  );
}
