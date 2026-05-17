import React, { useState, useEffect, useCallback } from "react";

export default function SchemaLibrary({ apiFetch, onSelect }) {
  const [schemas, setSchemas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadSchemas = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await apiFetch("/schemas");
      setSchemas(data.schemas || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    loadSchemas();
  }, [loadSchemas]);

  const handleDelete = useCallback(
    async (schemaId, e) => {
      e.stopPropagation();
      if (!confirm("Delete this schema? Cached results will be invalidated.")) {
        return;
      }
      try {
        await apiFetch(`/schemas/${schemaId}`, { method: "DELETE" });
        setSchemas((prev) => prev.filter((s) => s.id !== schemaId));
      } catch (e) {
        setError(e.message);
      }
    },
    [apiFetch]
  );

  const handleSelect = useCallback(
    (schema) => {
      onSelect({
        id: schema.id,
        name: schema.name,
        fields: schema.fields,
      });
    },
    [onSelect]
  );

  if (loading) {
    return (
      <div className="card">
        <h2>Saved Schemas</h2>
        <div className="loading-overlay">
          <div className="spinner" />
          <span>Loading schemas...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Saved Schemas</h2>

      {error && <div className="error-box">{error}</div>}

      {schemas.length === 0 ? (
        <p style={{ color: "#94a3b8", fontSize: "0.875rem" }}>
          No saved schemas yet. Build one below.
        </p>
      ) : (
        <div className="schema-list">
          {schemas.map((schema) => (
            <div
              key={schema.id}
              className="schema-item"
              onClick={() => handleSelect(schema)}
            >
              <div>
                <div className="schema-name">{schema.name}</div>
                <div className="schema-meta">
                  {schema.fields?.length || 0} field
                  {schema.fields?.length !== 1 ? "s" : ""}
                  {schema.updated_at && (
                    <>
                      {" "}
                      &middot; Updated{" "}
                      {new Date(schema.updated_at).toLocaleDateString()}
                    </>
                  )}
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSelect(schema);
                  }}
                >
                  Load
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  onClick={(e) => handleDelete(schema.id, e)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
