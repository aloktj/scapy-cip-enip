import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AssemblyMemberSummary,
  AssemblyMemberValue,
  AssemblyRuntimeResponse,
  AssemblySummary,
  CIPStatus
} from "../api/types";
import { formatApiError } from "../api/errors";
import { bytesToHex, hexToBytes } from "../utils/hex";
import { StatusBadge } from "./StatusBadge";

interface AssemblyRuntimeCardProps {
  assembly: AssemblySummary;
  sessionActive: boolean;
  pollIntervalMs: number;
  fetchAssembly: (alias: string) => Promise<AssemblyRuntimeResponse>;
  writeAssembly: (alias: string, payloadHex: string) => Promise<CIPStatus>;
}

interface MergedMember {
  key: string;
  definition: AssemblyMemberSummary;
  runtime?: AssemblyMemberValue;
}

interface BitToggleGroupProps {
  value: number;
  disabled: boolean;
  onToggle: (bit: number, next: boolean) => void;
}

function BitToggleGroup({ value, disabled, onToggle }: BitToggleGroupProps) {
  return (
    <div className="bit-toggle-group">
      {Array.from({ length: 8 }, (_, bit) => {
        const mask = 1 << bit;
        const checked = (value & mask) === mask;
        return (
          <label key={bit} className="bit-toggle">
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              onChange={(event) => onToggle(bit, event.target.checked)}
            />
            <span>{bit}</span>
          </label>
        );
      })}
    </div>
  );
}

export function AssemblyRuntimeCard({
  assembly,
  sessionActive,
  pollIntervalMs,
  fetchAssembly,
  writeAssembly
}: AssemblyRuntimeCardProps) {
  const [runtime, setRuntime] = useState<AssemblyRuntimeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [writeStatus, setWriteStatus] = useState<CIPStatus | null>(null);
  const [writePending, setWritePending] = useState(false);
  const [editingValues, setEditingValues] = useState<Record<string, string>>({});
  const isMounted = useRef(true);

  useEffect(() => {
    return () => {
      isMounted.current = false;
    };
  }, []);

  const fetchCurrent = useCallback(() => fetchAssembly(assembly.alias), [assembly.alias, fetchAssembly]);

  const writeCurrent = useCallback(
    (payloadHex: string) => writeAssembly(assembly.alias, payloadHex),
    [assembly.alias, writeAssembly]
  );

  const refresh = useCallback(async () => {
    if (!sessionActive || !isMounted.current) {
      return;
    }
    try {
      const response = await fetchCurrent();
      if (!isMounted.current) {
        return;
      }
      setRuntime(response);
      setError(null);
    } catch (err) {
      if (!isMounted.current) {
        return;
      }
      setError(formatApiError(err));
    }
  }, [fetchCurrent, sessionActive]);

  useEffect(() => {
    if (!sessionActive) {
      setRuntime(null);
      setError(null);
      return;
    }

    let timer: number | null = null;

    const poll = async () => {
      await refresh();
    };

    void poll();
    timer = window.setInterval(() => {
      void poll();
    }, pollIntervalMs);

    return () => {
      if (timer !== null) {
        window.clearInterval(timer);
      }
    };
  }, [pollIntervalMs, refresh, sessionActive]);

  useEffect(() => {
    setEditingValues({});
  }, [runtime?.timestamp, sessionActive]);

  const buildBuffer = useCallback(
    (requiredLength: number): Uint8Array | null => {
      const sourceHex = runtime?.payload_hex ?? null;
      if (sourceHex && sourceHex.length > 0) {
        const bytes = hexToBytes(sourceHex);
        if (bytes.length >= requiredLength) {
          return bytes;
        }
        const extended = new Uint8Array(requiredLength);
        extended.set(bytes);
        return extended;
      }
      if (assembly.size != null) {
        const length = Math.max(requiredLength, assembly.size);
        return new Uint8Array(length);
      }
      if (requiredLength > 0) {
        return new Uint8Array(requiredLength);
      }
      return null;
    },
    [assembly.size, runtime?.payload_hex]
  );

  const applyUpdate = useCallback(
    async (requiredLength: number, mutate: (buffer: Uint8Array) => void) => {
      if (!sessionActive) {
        setWriteError("Start a session before writing assemblies.");
        return;
      }
      const base = buildBuffer(requiredLength);
      if (!base) {
        setWriteError("Assembly size is unknown; unable to compose payload.");
        return;
      }
      const working = new Uint8Array(base);
      mutate(working);
      const payloadHex = bytesToHex(working);
      setWritePending(true);
      try {
        const status = await writeCurrent(payloadHex);
        if (!isMounted.current) {
          return;
        }
        setWriteStatus(status);
        setWriteError(null);
        await refresh();
      } catch (err) {
        if (!isMounted.current) {
          return;
        }
        setWriteError(formatApiError(err));
      } finally {
        if (isMounted.current) {
          setWritePending(false);
        }
      }
    },
    [buildBuffer, refresh, sessionActive, writeCurrent]
  );

  const mergedMembers = useMemo<MergedMember[]>(() => {
    const runtimeMembers = runtime?.members ?? [];
    const runtimeMap = new Map(runtimeMembers.map((member) => [member.name, member]));
    const list: MergedMember[] = assembly.members.map((member) => ({
      key: `${assembly.alias}:${member.name}`,
      definition: member,
      runtime: runtimeMap.get(member.name)
    }));
    for (const member of runtimeMembers) {
      if (!list.some((entry) => entry.definition.name === member.name)) {
        list.push({
          key: `${assembly.alias}:${member.name}`,
          definition: {
            name: member.name,
            datatype: member.datatype ?? null,
            direction: null,
            offset: member.offset ?? null,
            size: member.size ?? null,
            description: member.description ?? null
          },
          runtime: member
        });
      }
    }
    return list;
  }, [assembly.alias, assembly.members, runtime?.members]);

  const isOutputAssembly = assembly.direction === "output" || assembly.direction === "bidirectional";
  const runtimeReady = sessionActive && runtime !== null;
  const controlsDisabled = !runtimeReady || writePending;

  const lastUpdated = useMemo(() => {
    if (!runtime?.timestamp) {
      return null;
    }
    try {
      return new Date(runtime.timestamp * 1000).toLocaleTimeString();
    } catch (err) {
      return null;
    }
  }, [runtime?.timestamp]);

  const handleBitToggle = useCallback(
    (member: AssemblyMemberValue, bit: number, next: boolean) => {
      if (member.offset == null) {
        return;
      }
      const offset = member.offset;
      const requiredLength = offset + 1;
      void applyUpdate(requiredLength, (buffer) => {
        const current = buffer[offset] ?? 0;
        const mask = 1 << bit;
        buffer[offset] = next ? current | mask : current & ~mask;
      });
    },
    [applyUpdate]
  );

  const commitNumericValue = useCallback(
    async (member: AssemblyMemberValue, raw: string, key: string) => {
      if (member.offset == null || member.size == null || member.size <= 0) {
        return;
      }
      const trimmed = raw.trim();
      if (!trimmed) {
        setEditingValues((prev) => {
          const nextValues = { ...prev };
          delete nextValues[key];
          return nextValues;
        });
        return;
      }
      const numeric = Number(trimmed);
      if (!Number.isFinite(numeric)) {
        return;
      }
      const size = member.size;
      const offset = member.offset;
      const maxValue = Math.pow(256, size) - 1;
      const clamped = Math.min(Math.max(0, Math.round(numeric)), maxValue);
      if (member.int_value != null && clamped === member.int_value) {
        setEditingValues((prev) => {
          const nextValues = { ...prev };
          delete nextValues[key];
          return nextValues;
        });
        return;
      }
      await applyUpdate(offset + size, (buffer) => {
        let value = clamped;
        for (let index = 0; index < size; index += 1) {
          buffer[offset + index] = value & 0xff;
          value >>= 8;
        }
      });
      setEditingValues((prev) => {
        const nextValues = { ...prev };
        delete nextValues[key];
        return nextValues;
      });
    },
    [applyUpdate]
  );

  const handlePresetValue = useCallback(
    (member: AssemblyMemberValue, key: string, preset: "set" | "clear") => {
      if (member.offset == null || member.size == null || member.size <= 0) {
        return;
      }
      const size = member.size;
      const offset = member.offset;
      const maxValue = Math.pow(256, size) - 1;
      const targetValue = preset === "set" ? maxValue : 0;
      void applyUpdate(offset + size, (buffer) => {
        let value = targetValue;
        for (let index = 0; index < size; index += 1) {
          buffer[offset + index] = value & 0xff;
          value >>= 8;
        }
      });
      setEditingValues((prev) => {
        const nextValues = { ...prev };
        delete nextValues[key];
        return nextValues;
      });
    },
    [applyUpdate]
  );

  return (
    <div className="card assembly-card">
      <div className="assembly-card-header">
        <div>
          <h3>{assembly.alias}</h3>
          <p className="muted-text">
            Class {assembly.class_id} · Instance {assembly.instance_id} · {assembly.direction} assembly
          </p>
          {typeof assembly.size === "number" && (
            <p className="muted-text">Configured size: {assembly.size} bytes</p>
          )}
          {lastUpdated && <p className="muted-text">Last update: {lastUpdated}</p>}
        </div>
        <div className="assembly-status-column">
          <StatusBadge status={runtime?.status} />
          {writeStatus && <StatusBadge status={writeStatus} />}
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}
      {writeError && <p className="error-text">{writeError}</p>}
      {writePending && <p className="muted-text">Writing output payload…</p>}
      {!sessionActive && (
        <p className="muted-text">Start a session to load live values for this assembly.</p>
      )}

      {runtime?.payload_hex ? (
        <div className="payload-section">
          <h4>Payload</h4>
          <pre className="data-block">{runtime.payload_hex}</pre>
        </div>
      ) : (
        <div className="payload-section">
          <h4>Payload</h4>
          <p className="muted-text">No payload received yet.</p>
        </div>
      )}

      {mergedMembers.length === 0 ? (
        <p className="muted-text">No members declared for this assembly.</p>
      ) : (
        <div className="table-wrapper">
          <table className="assembly-table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Offset</th>
                <th>Size</th>
                <th>Datatype</th>
                <th>Description</th>
                <th>Raw</th>
                <th>Integer</th>
                <th>Controls</th>
              </tr>
            </thead>
            <tbody>
              {mergedMembers.map(({ key, definition, runtime: runtimeMember }) => {
                const effectiveMember: AssemblyMemberValue = {
                  name: definition.name,
                  offset: runtimeMember?.offset ?? definition.offset ?? null,
                  size: runtimeMember?.size ?? definition.size ?? null,
                  datatype: runtimeMember?.datatype ?? definition.datatype ?? null,
                  description: runtimeMember?.description ?? definition.description ?? null,
                  raw_hex: runtimeMember?.raw_hex ?? "",
                  int_value: runtimeMember?.int_value ?? null
                };
                const displayRaw = effectiveMember.raw_hex || "--";
                const displayInt =
                  effectiveMember.int_value != null ? effectiveMember.int_value.toString() : "--";
                const draftValue = editingValues[key];
                const isBitEditable =
                  isOutputAssembly &&
                  effectiveMember.size === 1 &&
                  effectiveMember.offset != null &&
                  runtimeReady;
                const bitValue = Number.parseInt(effectiveMember.raw_hex || "0", 16);
                const normalisedBitValue = Number.isNaN(bitValue) ? 0 : bitValue & 0xff;
                const showNumericEditor =
                  isOutputAssembly &&
                  effectiveMember.int_value != null &&
                  effectiveMember.size != null &&
                  effectiveMember.offset != null;
                const canPresetValue =
                  isOutputAssembly &&
                  effectiveMember.size != null &&
                  effectiveMember.size > 0 &&
                  effectiveMember.offset != null;
                let controls: ReactNode = <span className="read-only-tag">Read only</span>;
                if (!isOutputAssembly) {
                  controls = <span className="read-only-tag">Read only</span>;
                } else if (!sessionActive) {
                  controls = <span className="read-only-tag">Session inactive</span>;
                } else if (!runtimeReady) {
                  controls = <span className="read-only-tag">Awaiting data</span>;
                } else {
                  const elements: ReactNode[] = [];
                  if (isBitEditable) {
                    elements.push(
                      <BitToggleGroup
                        key={`${key}-bits`}
                        value={normalisedBitValue}
                        disabled={controlsDisabled}
                        onToggle={(bit, next) => handleBitToggle(effectiveMember, bit, next)}
                      />
                    );
                  }
                  if (showNumericEditor) {
                    elements.push(
                      <input
                        key={`${key}-numeric`}
                        type="number"
                        inputMode="numeric"
                        className="numeric-input"
                        value={draftValue ?? (effectiveMember.int_value?.toString() ?? "")}
                        disabled={controlsDisabled}
                        onChange={(event) =>
                          setEditingValues((prev) => ({ ...prev, [key]: event.target.value }))
                        }
                        onBlur={(event) => {
                          void commitNumericValue(
                            effectiveMember,
                            event.target.value,
                            key
                          );
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.currentTarget.blur();
                          }
                        }}
                      />
                    );
                  }
                  if (!elements.length) {
                    elements.push(<span key={`${key}-no-editor`}>--</span>);
                  }
                  if (canPresetValue) {
                    elements.push(
                      <div key={`${key}-presets`} className="control-button-row">
                        <button
                          type="button"
                          className="secondary-button compact-button"
                          disabled={controlsDisabled}
                          onClick={() => handlePresetValue(effectiveMember, key, "set")}
                        >
                          Set
                        </button>
                        <button
                          type="button"
                          className="secondary-button compact-button"
                          disabled={controlsDisabled}
                          onClick={() => handlePresetValue(effectiveMember, key, "clear")}
                        >
                          Clear
                        </button>
                      </div>
                    );
                  }
                  controls = <div className="control-stack">{elements}</div>;
                }

                const rowClass = !isOutputAssembly ? "read-only-row" : undefined;

                return (
                  <tr key={key} className={rowClass}>
                    <td>
                      <div className="member-name">
                        <span>{definition.name}</span>
                        {definition.direction && (
                          <span className="member-direction">{definition.direction}</span>
                        )}
                      </div>
                    </td>
                    <td>{
                      effectiveMember.offset != null ? effectiveMember.offset : "--"
                    }</td>
                    <td>{
                      effectiveMember.size != null ? `${effectiveMember.size} bytes` : "--"
                    }</td>
                    <td>{effectiveMember.datatype ?? "--"}</td>
                    <td>{effectiveMember.description ?? "--"}</td>
                    <td>
                      <code>{displayRaw}</code>
                    </td>
                    <td>{displayInt}</td>
                    <td>{controls}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
