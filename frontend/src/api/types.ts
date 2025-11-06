export interface CIPStatus {
  code?: number | null;
  message?: string | null;
}

export interface ConnectionStatus {
  connected: boolean;
  session_id: number;
  enip_connection_id: number;
  sequence: number;
  last_status: CIPStatus;
}

export interface SessionResponse {
  session_id: string;
  connection: ConnectionStatus;
}

export interface AssemblyQueryParams {
  class_id: number;
  instance_id: number;
  total_size: number;
}

export interface AssemblyReadResponse {
  class_id: number;
  instance_id: number;
  data_hex: string;
  word_values?: number[];
  timestamp: number;
  status: CIPStatus;
}

export interface CIPPathModel {
  class_id?: number;
  instance_id?: number;
  member_id?: number;
  attribute_id?: number;
  symbolic?: string;
}

export interface AssemblyWritePayload {
  attribute_id: number;
  value_hex: string;
  path?: CIPPathModel | null;
}

export interface CommandRequestPayload {
  service: number;
  path: CIPPathModel;
  payload_hex?: string | null;
  transport?: "rr" | "rr_cm" | "rr_mr" | "unit";
}

export interface CommandResponse {
  status: CIPStatus;
  payload_hex: string;
}

export interface SessionDiagnosticsResponse {
  session_id: string;
  connection: ConnectionStatus;
  keep_alive_pattern_hex: string;
  keep_alive_active: boolean;
  last_activity: number;
}

export interface ApiErrorShape {
  detail?: string | Record<string, unknown>;
}
