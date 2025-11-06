import type {
  AssemblyRuntimeResponse,
  AssemblySummary,
  CIPStatus
} from "../api/types";
import { AssemblyRuntimeCard } from "./AssemblyRuntimeCard";

interface AssemblyCatalogProps {
  assemblies: AssemblySummary[];
  sessionActive: boolean;
  pollIntervalMs: number;
  fetchAssembly: (alias: string) => Promise<AssemblyRuntimeResponse>;
  writeAssembly: (alias: string, payloadHex: string) => Promise<CIPStatus>;
}

export function AssemblyCatalog({
  assemblies,
  sessionActive,
  pollIntervalMs,
  fetchAssembly,
  writeAssembly
}: AssemblyCatalogProps) {
  if (!assemblies.length) {
    return (
      <div className="card">
        <h2>Assembly catalog</h2>
        <p style={{ color: "#475569" }}>
          Upload a configuration XML to browse assemblies and live payload data.
        </p>
      </div>
    );
  }

  return (
    <div className="assembly-grid">
      {assemblies.map((assembly) => (
        <AssemblyRuntimeCard
          key={assembly.alias}
          assembly={assembly}
          sessionActive={sessionActive}
          pollIntervalMs={pollIntervalMs}
          fetchAssembly={fetchAssembly}
          writeAssembly={writeAssembly}
        />
      ))}
    </div>
  );
}
