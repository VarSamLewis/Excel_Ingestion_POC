import React, { useState, useCallback } from "react";

const FIELD_TYPES = ["string", "number", "integer", "boolean", "date"];

const EMPTY_FIELD = {
  name: "",
  field_type: "string",
  description: "",
  required: true,
};

export default function SchemaEditor({ initialSchema, onReady }) {
  const [name, setName] = useState(initialSchema?.name || "");
  const [fields, setFields] = useState(
    initialSchema?.fields?.length
      ? initialSchema.fields
      : [{ ...EMPTY_FIELD }]
  );

  const addField = useCallback(() => {
    setFields((prev) => [...prev, { ...EMPTY_FIELD }]);
  }, []);

  const removeField = useCallback((index) => {
    setFields((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateField = useCallback((index, key, value) => {
    setFields((prev) =>
      prev.map((f, i) => (i === index ? { ...f, [key]: value } : f))
    );
  }, []);

  const handleSubmit = useCallback(() => {
    // Basic validation
    if (!name.trim()) return;
    const validFields = fields.filter((f) => f.name.trim());
    if (validFields.length === 0) return;

    onReady({
      name: name.trim(),
      fields: validFields,
      id: initialSchema?.id || "",
    });
  }, [name, fields, initialSchema, onReady]);

  const isValid = name.trim() && fields.some((f) => f.name.trim());

  return (
    <div className="card">
      <h2>Schema Editor</h2>

      <div className="form-group">
        <label htmlFor="schema-name">Schema Name</label>
        <input
          id="schema-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Acme Q1 Report"
        />
      </div>

      <h3>Fields</h3>

      {/* Header row */}
      <div className="field-row" style={{ fontWeight: 600, fontSize: "0.75rem", color: "#94a3b8", textTransform: "uppercase" }}>
        <span>Field Name</span>
        <span>Type</span>
        <span>Instruction to the AI</span>
        <span>Req</span>
        <span></span>
      </div>

      {fields.map((field, i) => (
        <div key={i} className="field-row">
          <input
            type="text"
            value={field.name}
            onChange={(e) => updateField(i, "name", e.target.value)}
            placeholder="e.g. supplier_name"
          />

          <select
            value={field.field_type}
            onChange={(e) => updateField(i, "field_type", e.target.value)}
          >
            {FIELD_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          <textarea
            value={field.description}
            onChange={(e) => updateField(i, "description", e.target.value)}
            placeholder="Be specific. List alternative column names the AI should look for, e.g. 'full legal name of the company, may appear as client, buyer or account name'"
            rows={2}
          />

          <input
            type="checkbox"
            checked={field.required}
            onChange={(e) => updateField(i, "required", e.target.checked)}
            title="Required field"
            style={{ width: "auto", margin: "0.5rem" }}
          />

          <button
            className="btn btn-danger btn-sm"
            onClick={() => removeField(i)}
            disabled={fields.length <= 1}
            title="Remove field"
          >
            X
          </button>
        </div>
      ))}

      <div style={{ display: "flex", gap: "0.75rem", marginTop: "1rem" }}>
        <button className="btn btn-secondary" onClick={addField}>
          + Add Field
        </button>
        <button
          className="btn btn-primary"
          onClick={handleSubmit}
          disabled={!isValid}
        >
          Use This Schema
        </button>
      </div>
    </div>
  );
}
