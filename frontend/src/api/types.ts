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
  host: string;
  port: number;
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
  host: string;
  port: number;
  keep_alive_pattern_hex: string;
  keep_alive_active: boolean;
  last_activity: number;
}

export interface ApiErrorShape {
  detail?: string | Record<string, unknown>;
}

export interface AssemblyMemberValue {
  name: string;
  offset?: number | null;
  size?: number | null;
  datatype?: string | null;
  description?: string | null;
  raw_hex: string;
  int_value?: number | null;
}

export interface AssemblyRuntimeResponse {
  alias: string;
  direction: string;
  size?: number | null;
  class_id: number;
  instance_id: number;
  payload_hex?: string | null;
  timestamp?: number | null;
  status: CIPStatus;
  word_values?: number[] | null;
  members: AssemblyMemberValue[];
}

export interface AssemblyMemberSummary {
  name: string;
  datatype?: string | null;
  direction?: string | null;
  offset?: number | null;
  size?: number | null;
  description?: string | null;
}

export interface AssemblySummary {
  alias: string;
  class_id: number;
  instance_id: number;
  direction: string;
  size?: number | null;
  members: AssemblyMemberSummary[];
}

export interface DeviceIdentity {
  name?: string | null;
  vendor?: string | null;
  product_code?: string | null;
  revision?: string | null;
  serial_number?: string | null;
}

export interface ConfigurationStatus {
  loaded: boolean;
  identity?: DeviceIdentity | null;
  assemblies: AssemblySummary[];
}
