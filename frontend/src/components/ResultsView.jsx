import React, { useState, useMemo, useCallback } from "react";

const PAGE_SIZE = 25;

export default function ResultsView({ result, onReset }) {
  const [page, setPage] = useState(0);

  const data = result.data || [];
  const totalPages = Math.ceil(data.length / PAGE_SIZE);
  const pageData = useMemo(
    () => data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [data, page]
  );

  // Get column names from first row
  const columns = useMemo(() => {
    if (data.length === 0) return [];
    return Object.keys(data[0]).filter((k) => !k.startsWith("_"));
  }, [data]);

  const validation = result.validation;

  const handleExportJSON = useCallback(() => {
    const blob = new Blob([JSON.stringify(result, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `extraction_${result.excel_hash || "data"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [result]);

  return (
    <div>
      {/* Summary bar */}
      <div className="card" style={{ display: "flex", alignItems: "center", gap: "1.5rem", flexWrap: "wrap" }}>
        <div>
          <strong>{result.row_count}</strong> rows extracted
        </div>

        {validation && (
          <div
            className={`badge ${
              validation.confidence >= 0.7
                ? "badge-success"
                : validation.confidence >= 0.5
                ? "badge-warning"
                : "badge-error"
            }`}
          >
            Confidence: {(validation.confidence * 100).toFixed(0)}%
          </div>
        )}

        {result.cached && (
          <span className="badge badge-success">Cached</span>
        )}

        <div style={{ marginLeft: "auto", display: "flex", gap: "0.5rem" }}>
          <button className="btn btn-secondary btn-sm" onClick={handleExportJSON}>
            Export JSON
          </button>
          <button className="btn btn-primary btn-sm" onClick={onReset}>
            New Extraction
          </button>
        </div>
      </div>

      {/* Validation issues */}
      {validation?.issues?.length > 0 && (
        <div className="card">
          <h3>Validation Issues</h3>
          {validation.issues.map((issue, i) => (
            <div
              key={i}
              style={{
                padding: "0.5rem 0.75rem",
                marginBottom: "0.5rem",
                background: issue.severity === "error" ? "#fee2e2" : "#fef9c3",
                borderRadius: "0.375rem",
                fontSize: "0.8125rem",
              }}
            >
              <strong>{issue.field}:</strong> {issue.issue}
              {issue.row_examples?.length > 0 && (
                <span style={{ color: "#94a3b8" }}>
                  {" "}
                  (rows: {issue.row_examples.join(", ")})
                </span>
              )}
            </div>
          ))}
          {validation.summary && (
            <p style={{ fontSize: "0.8125rem", color: "#64748b", marginTop: "0.5rem" }}>
              {validation.summary}
            </p>
          )}
        </div>
      )}

      {/* Data table */}
      <div className="card">
        <h2>Extracted Data</h2>

        {data.length === 0 ? (
          <p style={{ color: "#94a3b8" }}>No data extracted.</p>
        ) : (
          <>
            <div className="results-table-wrapper">
              <table className="results-table">
                <thead>
                  <tr>
                    <th>#</th>
                    {columns.map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {pageData.map((row, i) => (
                    <tr key={i}>
                      <td style={{ color: "#94a3b8" }}>
                        {page * PAGE_SIZE + i + 1}
                      </td>
                      {columns.map((col) => (
                        <td key={col}>
                          {row[col] !== null && row[col] !== undefined
                            ? String(row[col])
                            : ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="pagination">
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                >
                  Previous
                </button>
                <span style={{ fontSize: "0.8125rem", color: "#64748b" }}>
                  Page {page + 1} of {totalPages}
                </span>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() =>
                    setPage((p) => Math.min(totalPages - 1, p + 1))
                  }
                  disabled={page >= totalPages - 1}
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
