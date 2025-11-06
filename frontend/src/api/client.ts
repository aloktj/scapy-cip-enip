import type {
  ApiErrorShape,
  AssemblyQueryParams,
  AssemblyReadResponse,
  AssemblyRuntimeResponse,
  AssemblyWritePayload,
  CIPStatus,
  CommandRequestPayload,
  CommandResponse,
  ConfigurationStatus,
  SessionDiagnosticsResponse,
  SessionResponse
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export class ApiError extends Error {
  public readonly status: number;
  public readonly payload?: ApiErrorShape;

  constructor(message: string, status: number, payload?: ApiErrorShape) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function parseJSON<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) {
    return {} as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch (error) {
    throw new ApiError("Failed to parse server response", response.status);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    },
    ...init
  });

  if (!response.ok) {
    let payload: ApiErrorShape | undefined;
    try {
      payload = await parseJSON<ApiErrorShape>(response);
    } catch (error) {
      // ignore parsing errors for error payloads
    }
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : response.statusText || "Unexpected API error";
    throw new ApiError(detail, response.status, payload);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return parseJSON<T>(response);
}

export const api = {
  startSession(): Promise<SessionResponse> {
    return request<SessionResponse>("/sessions", { method: "POST" });
  },

  stopSession(sessionId: string): Promise<SessionResponse> {
    return request<SessionResponse>(`/sessions/${sessionId}`, { method: "DELETE" });
  },

  getSession(sessionId: string): Promise<SessionResponse> {
    return request<SessionResponse>(`/sessions/${sessionId}`);
  },

  getDiagnostics(sessionId: string): Promise<SessionDiagnosticsResponse> {
    return request<SessionDiagnosticsResponse>(`/sessions/${sessionId}/diagnostics`);
  },

  readAssembly(
    sessionId: string,
    params: AssemblyQueryParams
  ): Promise<AssemblyReadResponse> {
    const query = new URLSearchParams({
      class_id: params.class_id.toString(),
      instance_id: params.instance_id.toString(),
      total_size: params.total_size.toString()
    }).toString();
    return request<AssemblyReadResponse>(`/sessions/${sessionId}/assemblies?${query}`);
  },

  writeAssembly(
    sessionId: string,
    path: string,
    payload: AssemblyWritePayload
  ): Promise<void> {
    return request(`/sessions/${sessionId}/assemblies/${encodeURIComponent(path)}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  },

  executeCommand(
    sessionId: string,
    payload: CommandRequestPayload
  ): Promise<CommandResponse> {
    return request<CommandResponse>(`/sessions/${sessionId}/commands`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  getAssemblyRuntime(sessionId: string, alias: string): Promise<AssemblyRuntimeResponse> {
    return request<AssemblyRuntimeResponse>(
      `/sessions/${sessionId}/assemblies/${encodeURIComponent(alias)}`
    );
  },

  writeAssemblyData(sessionId: string, alias: string, payloadHex: string): Promise<CIPStatus> {
    return request<CIPStatus>(`/sessions/${sessionId}/assemblies/${encodeURIComponent(alias)}`, {
      method: "PUT",
      body: JSON.stringify({ payload_hex: payloadHex })
    });
  },

  uploadConfiguration(xml: string): Promise<ConfigurationStatus> {
    return request<ConfigurationStatus>("/config", {
      method: "POST",
      body: JSON.stringify({ xml })
    });
  },

  getConfiguration(): Promise<ConfigurationStatus> {
    return request<ConfigurationStatus>("/config");
  }
};
