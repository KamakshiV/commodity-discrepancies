import type { AttributeMapping, CompareFieldsResponse } from "../types";

const STORAGE_KEY = "commodity_compare_mappings";

function mappingKey(m: AttributeMapping): string {
  return `${m.vbap_field}→${m.cmm_field}`;
}

/** Keep saved rows but add any new server defaults (e.g. LGORT) the user may lack. */
export function mergeWithDefaultMappings(
  saved: AttributeMapping[],
  defaults: AttributeMapping[]
): AttributeMapping[] {
  const seen = new Set(saved.map(mappingKey));
  const merged = saved.map((m) => ({ ...m }));
  for (const row of defaults) {
    if (!seen.has(mappingKey(row))) {
      merged.push({ ...row });
    }
  }
  return merged;
}

export function loadSavedMappings(
  defaults: AttributeMapping[]
): AttributeMapping[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as AttributeMapping[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        return mergeWithDefaultMappings(parsed, defaults);
      }
    }
  } catch {
    /* ignore */
  }
  return defaults.map((m) => ({ ...m }));
}

export function saveMappings(mappings: AttributeMapping[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(mappings));
}

export function clearSavedMappings() {
  localStorage.removeItem(STORAGE_KEY);
}

interface Props {
  fields: CompareFieldsResponse | null;
  mappings: AttributeMapping[];
  onChange: (mappings: AttributeMapping[]) => void;
  onReset: () => void;
}

function emptyRow(vbapFields: string[], cmmFields: string[]): AttributeMapping {
  return {
    vbap_field: vbapFields[0] ?? "",
    cmm_field: cmmFields[0] ?? "",
    enabled: true,
  };
}

export default function AttributeMappingPanel({
  fields,
  mappings,
  onChange,
  onReset,
}: Props) {
  if (!fields) {
    return (
      <section className="mapping-panel mapping-panel-inner">
        <p className="muted">Load data to configure VBAP ↔ CMM_VLOGP field mappings.</p>
      </section>
    );
  }

  const vbapFields = fields.vbap_fields;
  const cmmFields = fields.cmm_fields;
  const enabledCount = mappings.filter((m) => m.enabled && m.vbap_field && m.cmm_field).length;

  const updateRow = (index: number, patch: Partial<AttributeMapping>) => {
    const next = mappings.map((row, i) => (i === index ? { ...row, ...patch } : row));
    onChange(next);
    saveMappings(next);
  };

  const addRow = () => {
    const next = [...mappings, emptyRow(vbapFields, cmmFields)];
    onChange(next);
    saveMappings(next);
  };

  const removeRow = (index: number) => {
    const next = mappings.filter((_, i) => i !== index);
    onChange(next.length ? next : [emptyRow(vbapFields, cmmFields)]);
    saveMappings(next);
  };

  return (
    <section className="mapping-panel mapping-panel-inner">
      <div className="mapping-header">
        <div>
          <h2>Attribute Comparison Mapping</h2>
          <p className="muted">
            Map VBAP fields to CMM_VLOGP fields for deterministic mismatch detection.
            Defaults auto-map fields with the same name in both tables, then add preset
            pairs (e.g. KWMENG → QUANTITY). Join keys are fixed and not compared.
          </p>
        </div>
        <div className="mapping-actions">
          <button type="button" className="btn secondary" onClick={onReset}>
            Reset to defaults
          </button>
          <button type="button" className="btn secondary" onClick={addRow}>
            + Add mapping
          </button>
        </div>
      </div>

      <div className="join-keys">
        <div className="join-block">
          <span className="join-label">VBAP join</span>
          <code>{fields.vbap_join_keys.join(" + ")}</code>
          <span className="join-arrow">↔</span>
          <span className="join-label">CMM_VLOGP join</span>
          <code>{fields.cmm_join_keys.join(" + ")}</code>
        </div>
      </div>

      <div className="mapping-grid">
        <div className="mapping-grid-head">
          <div className="col-vbap">
            <span className="table-tag vbap">VBAP</span>
            <span>Sales Order Item field</span>
          </div>
          <div className="col-link" aria-hidden />
          <div className="col-cmm">
            <span className="table-tag cmm">CMM_VLOGP</span>
            <span>Commodity version field</span>
          </div>
          <div className="col-compare">Compare</div>
          <div className="col-actions" />
        </div>

        {mappings.map((row, index) => (
          <div
            key={`${index}-${row.vbap_field}-${row.cmm_field}`}
            className={`mapping-row ${row.enabled ? "" : "disabled"}`}
          >
            <div className="col-vbap">
              <select
                value={row.vbap_field}
                onChange={(e) => updateRow(index, { vbap_field: e.target.value })}
                aria-label={`VBAP field row ${index + 1}`}
              >
                {vbapFields.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-link" title="Maps to">
              ↔
            </div>
            <div className="col-cmm">
              <select
                value={row.cmm_field}
                onChange={(e) => updateRow(index, { cmm_field: e.target.value })}
                aria-label={`CMM_VLOGP field row ${index + 1}`}
              >
                {cmmFields.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </div>
            <div className="col-compare">
              <label className="compare-toggle">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  onChange={(e) => updateRow(index, { enabled: e.target.checked })}
                />
                <span>{row.enabled ? "On" : "Off"}</span>
              </label>
            </div>
            <div className="col-actions">
              <button
                type="button"
                className="btn-icon"
                onClick={() => removeRow(index)}
                disabled={mappings.length <= 1}
                title="Remove mapping"
                aria-label="Remove mapping"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>

      <p className="mapping-footer muted">
        {enabledCount} active mapping{enabledCount !== 1 ? "s" : ""} will be used when you run analysis.
      </p>
    </section>
  );
}
