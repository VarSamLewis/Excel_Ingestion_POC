import React, { useState, useCallback, useRef } from "react";

export default function FileUpload({ onUpload }) {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const inputRef = useRef(null);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file && isExcel(file)) {
        setSelectedFile(file);
      }
    },
    []
  );

  const handleInputChange = useCallback((e) => {
    const file = e.target.files[0];
    if (file && isExcel(file)) {
      setSelectedFile(file);
    }
  }, []);

  const handleUpload = useCallback(() => {
    if (selectedFile) {
      onUpload(selectedFile);
    }
  }, [selectedFile, onUpload]);

  return (
    <div className="card">
      <h2>Upload Excel File</h2>

      <div
        className={`dropzone ${dragOver ? "drag-over" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <p>
          {selectedFile
            ? null
            : "Drag and drop an Excel file here, or click to browse"}
        </p>

        {selectedFile && (
          <div className="file-info">
            <p>
              <strong>{selectedFile.name}</strong>
            </p>
            <p>{formatSize(selectedFile.size)}</p>
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xls"
          onChange={handleInputChange}
          style={{ display: "none" }}
        />
      </div>

      {selectedFile && (
        <div style={{ marginTop: "1rem", textAlign: "center" }}>
          <button className="btn btn-primary" onClick={handleUpload}>
            Process File
          </button>
        </div>
      )}
    </div>
  );
}

function isExcel(file) {
  return (
    file.name.endsWith(".xlsx") ||
    file.name.endsWith(".xls") ||
    file.type ===
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    file.type === "application/vnd.ms-excel"
  );
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
