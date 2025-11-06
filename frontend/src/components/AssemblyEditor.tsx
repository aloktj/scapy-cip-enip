import { useMemo, useState } from "react";
import { z } from "zod";
import type {
  AssemblyQueryParams,
  AssemblyReadResponse,
  AssemblyWritePayload
} from "../api/types";
import { StatusBadge } from "./StatusBadge";

const assemblyReadSchema = z.object({
  class_id: z.coerce.number().int().positive("Class ID must be a positive integer"),
  instance_id: z.coerce.number().int().positive("Instance ID must be a positive integer"),
  total_size: z
    .coerce
    .number()
    .int()
    .positive("Total size must be a positive integer")
    .max(0x1000, "Total size must be 4096 bytes or less")
});

const optionalNumber = z.preprocess(
  (value) => {
    if (value === undefined || value === null) {
      return undefined;
    }
    if (typeof value === "string" && value.trim() === "") {
      return undefined;
    }
    return Number(value);
  },
  z
    .number()
    .int({ message: "Value must be an integer" })
    .nonnegative("Value cannot be negative")
    .optional()
);

const assemblyWriteSchema = z.object({
  symbolic_path: z.string().min(1, "Provide a symbolic path for the assembly"),
  attribute_id: z.coerce.number().int().positive("Attribute ID must be a positive integer"),
  value_hex: z
    .string()
    .min(2, "Value must contain hexadecimal characters")
    .regex(/^[0-9a-fA-F]+$/, "Value must be hexadecimal")
    .refine((val) => val.length % 2 === 0, {
      message: "Hex string must contain an even number of characters"
    }),
  class_id: optionalNumber,
  instance_id: optionalNumber,
  member_id: optionalNumber,
  attribute_path_id: optionalNumber
});

interface AssemblyEditorProps {
  disabled: boolean;
  onRead: (params: AssemblyQueryParams) => Promise<AssemblyReadResponse>;
  onWrite: (path: string, payload: AssemblyWritePayload) => Promise<void>;
}

export function AssemblyEditor({ disabled, onRead, onWrite }: AssemblyEditorProps) {
  const [readForm, setReadForm] = useState({ class_id: "", instance_id: "", total_size: "64" });
  const [writeForm, setWriteForm] = useState({
    symbolic_path: "",
    attribute_id: "1",
    value_hex: "0000",
    class_id: "",
    instance_id: "",
    member_id: "",
    attribute_path_id: ""
  });

  const [readError, setReadError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [readLoading, setReadLoading] = useState(false);
  const [writeLoading, setWriteLoading] = useState(false);
  const [lastRead, setLastRead] = useState<AssemblyReadResponse | null>(null);
  const [writeSuccess, setWriteSuccess] = useState<string | null>(null);

  const readStatus = lastRead?.status;

  const wordValues = useMemo(() => lastRead?.word_values?.join(", "), [lastRead]);

  const handleRead = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setReadError(null);
    setReadLoading(true);
    setWriteSuccess(null);
    try {
      const parsed = assemblyReadSchema.parse(readForm);
      const payload: AssemblyQueryParams = {
        class_id: parsed.class_id,
        instance_id: parsed.instance_id,
        total_size: parsed.total_size
      };
      const result = await onRead(payload);
      setLastRead(result);
    } catch (error) {
      if (error instanceof z.ZodError) {
        setReadError(error.errors[0]?.message ?? "Invalid form input");
      } else {
        setReadError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setReadLoading(false);
    }
  };

  const handleWrite = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setWriteError(null);
    setWriteSuccess(null);
    setWriteLoading(true);
    try {
      const parsed = assemblyWriteSchema.parse(writeForm);
      const payload: AssemblyWritePayload = {
        attribute_id: parsed.attribute_id,
        value_hex: parsed.value_hex.toLowerCase(),
        path: {
          symbolic: parsed.symbolic_path,
          class_id: parsed.class_id,
          instance_id: parsed.instance_id,
          member_id: parsed.member_id,
          attribute_id: parsed.attribute_path_id
        }
      };
      await onWrite(parsed.symbolic_path, payload);
      setWriteSuccess(`Attribute 0x${parsed.attribute_id.toString(16)} successfully queued`);
    } catch (error) {
      if (error instanceof z.ZodError) {
        setWriteError(error.errors[0]?.message ?? "Invalid form input");
      } else {
        setWriteError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setWriteLoading(false);
    }
  };

  return (
    <div className="card">
      <h2>Assembly tools</h2>
      <div className="dashboard-grid" style={{ marginBottom: "1.5rem" }}>
        <div>
          <h3 style={{ marginBottom: "0.75rem" }}>Read assembly</h3>
          <form onSubmit={handleRead} className="form-grid">
            <div className="field-group">
              <label htmlFor="read-class">Class ID</label>
              <input
                id="read-class"
                type="number"
                inputMode="numeric"
                value={readForm.class_id}
                onChange={(event) => setReadForm((prev) => ({ ...prev, class_id: event.target.value }))}
                disabled={disabled || readLoading}
                required
              />
            </div>
            <div className="field-group">
              <label htmlFor="read-instance">Instance ID</label>
              <input
                id="read-instance"
                type="number"
                inputMode="numeric"
                value={readForm.instance_id}
                onChange={(event) =>
                  setReadForm((prev) => ({ ...prev, instance_id: event.target.value }))
                }
                disabled={disabled || readLoading}
                required
              />
            </div>
            <div className="field-group">
              <label htmlFor="read-size">Total size (bytes)</label>
              <input
                id="read-size"
                type="number"
                inputMode="numeric"
                value={readForm.total_size}
                onChange={(event) =>
                  setReadForm((prev) => ({ ...prev, total_size: event.target.value }))
                }
                disabled={disabled || readLoading}
                required
              />
            </div>
            {readError && <p className="error-text">{readError}</p>}
            <div className="form-actions">
              <button type="submit" disabled={disabled || readLoading}>
                {readLoading ? "Reading…" : "Read assembly"}
              </button>
              {lastRead && <StatusBadge status={readStatus} />}
            </div>
          </form>
        </div>

        <div>
          <h3 style={{ marginBottom: "0.75rem" }}>Write assembly attribute</h3>
          <form onSubmit={handleWrite} className="form-grid">
            <div className="field-group">
              <label htmlFor="write-symbolic">Symbolic path</label>
              <input
                id="write-symbolic"
                value={writeForm.symbolic_path}
                placeholder="Example: Assembly_A"
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, symbolic_path: event.target.value }))
                }
                disabled={disabled || writeLoading}
                required
              />
            </div>
            <div className="field-group">
              <label htmlFor="write-attribute">Attribute ID</label>
              <input
                id="write-attribute"
                type="number"
                inputMode="numeric"
                value={writeForm.attribute_id}
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, attribute_id: event.target.value }))
                }
                disabled={disabled || writeLoading}
                required
              />
            </div>
            <div className="field-group">
              <label htmlFor="write-value">Value (hex)</label>
              <input
                id="write-value"
                value={writeForm.value_hex}
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, value_hex: event.target.value }))
                }
                disabled={disabled || writeLoading}
                required
              />
            </div>
            <div className="field-group">
              <label htmlFor="write-class">Class ID (optional)</label>
              <input
                id="write-class"
                type="number"
                inputMode="numeric"
                value={writeForm.class_id}
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, class_id: event.target.value }))
                }
                disabled={disabled || writeLoading}
              />
            </div>
            <div className="field-group">
              <label htmlFor="write-instance">Instance ID (optional)</label>
              <input
                id="write-instance"
                type="number"
                inputMode="numeric"
                value={writeForm.instance_id}
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, instance_id: event.target.value }))
                }
                disabled={disabled || writeLoading}
              />
            </div>
            <div className="field-group">
              <label htmlFor="write-member">Member ID (optional)</label>
              <input
                id="write-member"
                type="number"
                inputMode="numeric"
                value={writeForm.member_id}
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, member_id: event.target.value }))
                }
                disabled={disabled || writeLoading}
              />
            </div>
            <div className="field-group">
              <label htmlFor="write-attribute-path">Attribute ID (path override)</label>
              <input
                id="write-attribute-path"
                type="number"
                inputMode="numeric"
                value={writeForm.attribute_path_id}
                onChange={(event) =>
                  setWriteForm((prev) => ({ ...prev, attribute_path_id: event.target.value }))
                }
                disabled={disabled || writeLoading}
              />
            </div>
            {writeError && <p className="error-text">{writeError}</p>}
            {writeSuccess && <p className="success-text">{writeSuccess}</p>}
            <div className="form-actions">
              <button type="submit" disabled={disabled || writeLoading}>
                {writeLoading ? "Writing…" : "Write attribute"}
              </button>
            </div>
          </form>
        </div>
      </div>

      {lastRead && (
        <div>
          <h3 style={{ marginBottom: "0.5rem" }}>Latest assembly snapshot</h3>
          <div className="data-block">
            <div>
              <strong>Timestamp:</strong> {new Date(lastRead.timestamp * 1000).toLocaleString()}
            </div>
            <div>
              <strong>Hex data:</strong> {lastRead.data_hex}
            </div>
            {wordValues && (
              <div>
                <strong>Words:</strong> {wordValues}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
