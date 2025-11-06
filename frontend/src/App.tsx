import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import type {
  AssemblyQueryParams,
  AssemblyReadResponse,
  AssemblyWritePayload,
  AssemblyRuntimeResponse,
  CIPStatus,
  ConfigurationStatus,
  SessionDiagnosticsResponse,
  SessionResponse
} from "./api/types";
import { api, ApiError, setAuthToken } from "./api/client";
import { formatApiError } from "./api/errors";
import { SessionDashboard } from "./components/SessionDashboard";
import { AssemblyEditor } from "./components/AssemblyEditor";
import { StatusBadge } from "./components/StatusBadge";
import { AssemblyCatalog } from "./components/AssemblyCatalog";
import { resolveStatusMessage } from "./statusMessages";
import "./App.css";

const DIAGNOSTICS_INTERVAL_MS = 4000;
const LAST_SESSION_HOST_KEY = "scapy-cip-enip:last-session-host";
const LAST_SESSION_PORT_KEY = "scapy-cip-enip:last-session-port";
const API_TOKEN_KEY = "scapy-cip-enip:api-token";

export default function App() {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<SessionDiagnosticsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);
  const [configuration, setConfiguration] = useState<ConfigurationStatus | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [configSuccess, setConfigSuccess] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [apiToken, setApiToken] = useState<string>(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return window.localStorage.getItem(API_TOKEN_KEY)?.trim() ?? "";
  });
  const [tokenDraft, setTokenDraft] = useState<string>(apiToken);
  const [tokenFeedback, setTokenFeedback] = useState<string | null>(null);
  const [sessionHost, setSessionHost] = useState<string>(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return window.localStorage.getItem(LAST_SESSION_HOST_KEY) ?? "";
  });
  const [sessionPort, setSessionPort] = useState<string>(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return window.localStorage.getItem(LAST_SESSION_PORT_KEY) ?? "";
  });

  const activeStatus = useMemo(() => diagnostics?.connection.last_status ?? session?.connection.last_status, [
    diagnostics,
    session
  ]);

  useEffect(() => {
    setAuthToken(apiToken);
    if (typeof window === "undefined") {
      return;
    }
    if (apiToken) {
      window.localStorage.setItem(API_TOKEN_KEY, apiToken);
    } else {
      window.localStorage.removeItem(API_TOKEN_KEY);
    }
  }, [apiToken]);

  useEffect(() => {
    let cancelled = false;

    const loadConfiguration = async () => {
      setConfigLoading(true);
      setConfigError(null);
      setConfigSuccess(null);
      try {
        const status = await api.getConfiguration();
        if (cancelled) {
          return;
        }
        setConfiguration(status);
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setConfiguration(null);
          setConfigError(
            apiToken
              ? "Authorization failed. Verify the bearer token saved below matches PLC_API_TOKEN."
              : "Provide the API bearer token below before managing the configuration."
          );
        } else {
          setConfigError(formatApiError(error));
        }
      } finally {
        if (!cancelled) {
          setConfigLoading(false);
        }
      }
    };

    void loadConfiguration();

    return () => {
      cancelled = true;
    };
  }, [apiToken]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (sessionHost) {
      window.localStorage.setItem(LAST_SESSION_HOST_KEY, sessionHost);
    } else {
      window.localStorage.removeItem(LAST_SESSION_HOST_KEY);
    }
  }, [sessionHost]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (sessionPort) {
      window.localStorage.setItem(LAST_SESSION_PORT_KEY, sessionPort);
    } else {
      window.localStorage.removeItem(LAST_SESSION_PORT_KEY);
    }
  }, [sessionPort]);

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
        const message = formatApiError(error);
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
      const trimmedHost = sessionHost.trim();
      const parsedPort = Number.parseInt(sessionPort, 10);
      const sanitizedPort = Number.isInteger(parsedPort) && parsedPort > 0 ? parsedPort : undefined;
      const newSession = await api.startSession(trimmedHost || undefined, sanitizedPort);
      setSession(newSession);
      setSessionHost(newSession.host);
      setSessionPort(newSession.port.toString());
    } catch (error) {
      setGlobalError(formatApiError(error));
    } finally {
      setLoading(false);
    }
  }, [sessionHost, sessionPort]);

  const handleStop = useCallback(async () => {
    if (!session) {
      return;
    }
    setLoading(true);
    setGlobalError(null);
    try {
      const stopped = await api.stopSession(session.session_id);
      setSession(stopped);
      setSessionHost(stopped.host);
      setSessionPort(stopped.port.toString());
      setDiagnostics(null);
    } catch (error) {
      setGlobalError(formatApiError(error));
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

  const handleHostChange = useCallback((value: string) => {
    setSessionHost(value);
  }, []);

  const handlePortChange = useCallback((value: string) => {
    setSessionPort(value);
  }, []);

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

  const handleBrowseClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) {
        return;
      }
      setConfigSuccess(null);
      setConfigError(null);
      setConfigLoading(true);
      void file
        .text()
        .then((xml) => api.uploadConfiguration(xml))
        .then((status) => {
          setConfiguration(status);
          setConfigSuccess(
            `Loaded ${status.identity?.name ?? "configuration"} with ${status.assemblies.length} assemblies.`
          );
        })
        .catch((error) => {
          if (error instanceof ApiError && error.status === 401) {
            setConfigError(
              apiToken
                ? "Authorization failed. Verify the bearer token saved below matches PLC_API_TOKEN."
                : "Provide the API bearer token below before managing the configuration."
            );
          } else {
            setConfigError(formatApiError(error));
          }
        })
        .finally(() => {
          setConfigLoading(false);
        });
    },
    [apiToken]
  );

  const handleTokenDraftChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setTokenDraft(event.target.value);
    setTokenFeedback(null);
  }, []);

  const handleTokenSave = useCallback(() => {
    const trimmed = tokenDraft.trim();
    setApiToken(trimmed);
    setTokenDraft(trimmed);
    setTokenFeedback(trimmed ? "Bearer token saved for API requests." : "Cleared saved bearer token.");
  }, [tokenDraft]);

  const handleTokenClear = useCallback(() => {
    setTokenDraft("");
    setApiToken("");
    setTokenFeedback("Cleared saved bearer token.");
  }, []);

  const tokenSaveDisabled = useMemo(() => tokenDraft.trim() === apiToken, [apiToken, tokenDraft]);

  const handleFileInput = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      handleFiles(event.target.files);
      event.target.value = "";
    },
    [handleFiles]
  );

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragActive(false);
      handleFiles(event.dataTransfer.files);
    },
    [handleFiles]
  );

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragActive(false);
  }, []);

  const fetchAssemblyRuntime = useCallback(
    async (alias: string): Promise<AssemblyRuntimeResponse> => {
      if (!session) {
        throw new Error("Start a session before inspecting assemblies");
      }
      return api.getAssemblyRuntime(session.session_id, alias);
    },
    [session]
  );

  const writeAssemblyData = useCallback(
    async (alias: string, payloadHex: string): Promise<CIPStatus> => {
      if (!session) {
        throw new Error("Start a session before writing assemblies");
      }
      return api.writeAssemblyData(session.session_id, alias, payloadHex);
    },
    [session]
  );

  const assemblies = configuration?.assemblies ?? [];
  const deviceIdentity = configuration?.identity;

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
          host={sessionHost}
          port={sessionPort}
          loading={loading}
          onHostChange={handleHostChange}
          onPortChange={handlePortChange}
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

      <div className="card">
        <h2>Device configuration</h2>
        <div
          className={`config-dropzone${dragActive ? " dragging" : ""}`}
          onDragOver={handleDragOver}
          onDragEnter={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <p className="muted-text" style={{ marginBottom: "0.75rem" }}>
            Drop a Rockwell/Studio 5000 XML export or browse to upload a configuration.
          </p>
          <button type="button" onClick={handleBrowseClick} disabled={configLoading}>
            {configLoading ? "Uploading…" : "Browse XML"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xml,text/xml,application/xml"
            hidden
            onChange={handleFileInput}
          />
        </div>
        <div className="field-group" style={{ marginTop: "1rem" }}>
          <label htmlFor="api-token">API bearer token</label>
          <div className="token-controls">
            <input
              id="api-token"
              type="password"
              className="token-input"
              placeholder="Paste the PLC_API_TOKEN value"
              value={tokenDraft}
              onChange={handleTokenDraftChange}
              autoComplete="off"
            />
            <button type="button" onClick={handleTokenSave} disabled={tokenSaveDisabled}>
              Save token
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={handleTokenClear}
              disabled={!apiToken && !tokenDraft}
            >
              Clear
            </button>
          </div>
          <p className="muted-text">
            This value is stored locally in your browser and sent with all API requests.
          </p>
          {tokenFeedback && (
            <p className="success-text" style={{ marginTop: "0.5rem" }}>{tokenFeedback}</p>
          )}
        </div>
        {configError && <p className="error-text" style={{ marginTop: "0.75rem" }}>{configError}</p>}
        {configSuccess && (
          <p className="success-text" style={{ marginTop: "0.75rem" }}>{configSuccess}</p>
        )}
        {configuration && (
          <div className="config-summary" style={{ marginTop: "1rem" }}>
            <div className="config-summary-grid">
              <div>
                <span className="config-label">Status</span>
                <span className="config-value">{configuration.loaded ? "Loaded" : "Not loaded"}</span>
              </div>
              <div>
                <span className="config-label">Device</span>
                <span className="config-value">{deviceIdentity?.name ?? "—"}</span>
              </div>
              <div>
                <span className="config-label">Vendor</span>
                <span className="config-value">{deviceIdentity?.vendor ?? "—"}</span>
              </div>
              <div>
                <span className="config-label">Product code</span>
                <span className="config-value">{deviceIdentity?.product_code ?? "—"}</span>
              </div>
              <div>
                <span className="config-label">Revision</span>
                <span className="config-value">{deviceIdentity?.revision ?? "—"}</span>
              </div>
              <div>
                <span className="config-label">Serial</span>
                <span className="config-value">{deviceIdentity?.serial_number ?? "—"}</span>
              </div>
            </div>
            <p className="muted-text" style={{ marginTop: "0.75rem" }}>
              Assemblies discovered: <strong>{assemblies.length}</strong>
            </p>
          </div>
        )}
      </div>

      <AssemblyCatalog
        assemblies={assemblies}
        sessionActive={Boolean(session)}
        pollIntervalMs={DIAGNOSTICS_INTERVAL_MS}
        fetchAssembly={fetchAssemblyRuntime}
        writeAssembly={writeAssemblyData}
      />

      <AssemblyEditor disabled={!session || loading} onRead={handleRead} onWrite={handleWrite} />
    </div>
  );
}
