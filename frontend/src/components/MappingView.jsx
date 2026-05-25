import React, { useState, useCallback } from "react";

const TRANSFORMS = [
  "identity",
  "strip",
  "to_date",
  "to_number",
  "to_boolean",
  "to_string",
  "split_comma",
  "to_integer",
  "regex_extract",
  "concat",
  "conditional",
  "uppercase",
  "lowercase",
  "default_value",
  "trim_whitespace",
  "substring",
];

export default function MappingView({ mapping, onConfirm, onReExtract }) {
  const [editedMappings, setEditedMappings] = useState(
    mapping.mappings.map((m) => ({ ...m }))
  );
  const [hasEdits, setHasEdits] = useState(false);

  const updateMapping = useCallback((index, key, value) => {
    setEditedMappings((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [key]: value } : m))
    );
    setHasEdits(true);
  }, []);

  const handleConfirm = useCallback(() => {
    onConfirm();
  }, [onConfirm]);

  const handleReExtract = useCallback(() => {
    const editedMapping = {
      ...mapping,
      mappings: editedMappings,
    };
    onReExtract(editedMapping);
  }, [mapping, editedMappings, onReExtract]);

  return (
    <div className="card">
      <h2>Review Mapping</h2>

      <p style={{ color: "#64748b", fontSize: "0.875rem", marginBottom: "1rem" }}>
        GPT-4o inferred the following column-to-field mapping. You can correct
        any assignments below and re-run extraction without another LLM call.
      </p>

      {/* Mapping table header */}
      <div className="mapping-row mapping-header">
        <span>Source Column</span>
        <span>Target Field</span>
        <span>Transform</span>
        <span>Notes</span>
      </div>

      {/* Mapping rows */}
      {editedMappings.map((m, i) => (
        <div key={i} className="mapping-row">
          <input
            type="text"
            value={m.source_col}
            onChange={(e) => updateMapping(i, "source_col", e.target.value)}
            style={{
              padding: "0.375rem 0.5rem",
              border: "1px solid #d1d5db",
              borderRadius: "0.375rem",
              fontSize: "0.875rem",
              width: "100%",
            }}
          />

          <span style={{ fontWeight: 500, color: "#0f172a" }}>
            {m.target_field}
          </span>

          <select
            value={m.transform}
            onChange={(e) => updateMapping(i, "transform", e.target.value)}
            style={{
              padding: "0.375rem 0.5rem",
              border: "1px solid #d1d5db",
              borderRadius: "0.375rem",
              fontSize: "0.8125rem",
              width: "100%",
            }}
          >
            {TRANSFORMS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          <span style={{ fontSize: "0.8125rem", color: "#64748b" }}>
            {m.notes}
          </span>
        </div>
      ))}

      {/* Reasoning */}
      {mapping.reasoning && (
        <div className="reasoning-box">
          <strong>AI Reasoning:</strong> {mapping.reasoning}
        </div>
      )}

      {/* Sheet info */}
      <div
        style={{
          marginTop: "1rem",
          fontSize: "0.8125rem",
          color: "#94a3b8",
        }}
      >
        Sheet: <strong>{mapping.sheet_name}</strong> | Header row:{" "}
        <strong>{mapping.header_row}</strong> | Data starts at row:{" "}
        <strong>{mapping.data_start_row}</strong>
      </div>

      {/* Actions */}
      <div
        style={{
          display: "flex",
          gap: "0.75rem",
          marginTop: "1.5rem",
          justifyContent: "flex-end",
        }}
      >
        {hasEdits && (
          <button className="btn btn-secondary" onClick={handleReExtract}>
            Re-run Extraction with Changes
          </button>
        )}
        <button className="btn btn-primary" onClick={handleConfirm}>
          Confirm &amp; View Results
        </button>
      </div>
    </div>
  );
}
