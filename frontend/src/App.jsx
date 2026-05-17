import React, { useState, useCallback } from "react";

import SchemaLibrary from "./components/SchemaLibrary";
import SchemaEditor from "./components/SchemaEditor";
import FileUpload from "./components/FileUpload";
import MappingView from "./components/MappingView";
import ResultsView from "./components/ResultsView";

// ── Config ──────────────────────────────────────────────────────

const AZURE_CLIENT_ID = import.meta.env.VITE_AZURE_CLIENT_ID || "";
const AZURE_TENANT_ID = import.meta.env.VITE_AZURE_TENANT_ID || "";
const API_URL = import.meta.env.VITE_API_URL || "";
const AUTH_ENABLED = Boolean(AZURE_CLIENT_ID && AZURE_TENANT_ID);

// ── MSAL (lazy — only initialised when auth is configured) ──────

let msalInstance = null;
let MsalProvider = null;
let AuthenticatedTemplate = null;
let UnauthenticatedTemplate = null;
let useMsalHook = null;
let useIsAuthenticatedHook = null;

if (AUTH_ENABLED) {
  // Dynamic imports are resolved at build time by Vite since the
  // packages are in node_modules — this branch is tree-shaken if
  // AUTH_ENABLED is false at build time.
  const msalBrowser = await import("@azure/msal-browser");
  const msalReact = await import("@azure/msal-react");

  MsalProvider = msalReact.MsalProvider;
  AuthenticatedTemplate = msalReact.AuthenticatedTemplate;
  UnauthenticatedTemplate = msalReact.UnauthenticatedTemplate;
  useMsalHook = msalReact.useMsal;
  useIsAuthenticatedHook = msalReact.useIsAuthenticated;

  const msalConfig = {
    auth: {
      clientId: AZURE_CLIENT_ID,
      authority: `https://login.microsoftonline.com/${AZURE_TENANT_ID}`,
      redirectUri: window.location.origin,
    },
    cache: {
      cacheLocation: "sessionStorage",
      storeAuthStateInCookie: false,
    },
  };

  msalInstance = new msalBrowser.PublicClientApplication(msalConfig);
  await msalInstance.initialize();

  msalInstance.addEventCallback((event) => {
    if (
      event.eventType === msalBrowser.EventType.LOGIN_SUCCESS &&
      event.payload?.account
    ) {
      msalInstance.setActiveAccount(event.payload.account);
    }
  });
}

const loginRequest = { scopes: ["openid", "profile", "User.Read"] };

// ── API helper ──────────────────────────────────────────────────

async function apiFetch(path, options = {}, msal) {
  const headers = { ...options.headers };

  // Attach Bearer token if MSAL is active
  const account = msal?.getActiveAccount?.();
  if (account) {
    try {
      const tokenResponse = await msal.acquireTokenSilent({
        ...loginRequest,
        account,
      });
      headers["Authorization"] = `Bearer ${tokenResponse.accessToken}`;
    } catch {
      // Token acquisition failed — proceed without auth (local dev)
    }
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const err = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(err.detail || err.error || "Request failed");
  }

  return response.json();
}

// ── Step names ──────────────────────────────────────────────────

const STEPS = ["Schema", "Upload", "Review", "Results"];

// ── Main app content ────────────────────────────────────────────

function AppContent() {
  // When auth is enabled, use the real MSAL hooks; otherwise stubs
  const msal = AUTH_ENABLED ? useMsalHook() : { instance: null, accounts: [] };
  const isAuthenticated = AUTH_ENABLED
    ? useIsAuthenticatedHook()
    : true; // No auth = always "authenticated"

  const { instance, accounts } = msal;

  const [step, setStep] = useState(0);
  const [schema, setSchema] = useState(null);
  const [file, setFile] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const account = accounts?.[0];
  const userName = account?.name || account?.username || "User";

  // ── Auth ──────────────────────────────────────────────────────

  const handleLogin = () => {
    instance?.loginPopup(loginRequest).catch((e) => {
      setError(e.message);
    });
  };

  const handleLogout = () => {
    instance?.logoutPopup();
  };

  // ── Step 1: Schema selected ───────────────────────────────────

  const handleSchemaReady = useCallback((schemaDefinition) => {
    setSchema(schemaDefinition);
    setStep(1);
    setError("");
  }, []);

  // ── Step 2: File uploaded -> call /ingest ──────────────────────

  const handleFileUpload = useCallback(
    async (uploadedFile) => {
      setFile(uploadedFile);
      setLoading(true);
      setError("");

      try {
        const formData = new FormData();
        formData.append("file", uploadedFile);

        const params = new URLSearchParams({
          schema_name: schema.name,
          schema_json: JSON.stringify(schema),
        });

        const data = await apiFetch(
          `/ingest?${params.toString()}`,
          { method: "POST", body: formData },
          instance
        );

        setMapping(data.mapping);
        setResult(data);
        setStep(2);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    },
    [schema, instance]
  );

  // ── Step 3: Confirm mapping -> show results ────────────────────

  const handleConfirmMapping = useCallback(() => {
    setStep(3);
  }, []);

  // ── Step 3 alt: Re-run extraction with edited mapping ─────────

  const handleReExtract = useCallback(
    async (editedMapping) => {
      if (!file) return;
      setLoading(true);
      setError("");

      try {
        const formData = new FormData();
        formData.append("file", file);

        const params = new URLSearchParams({
          mapping_json: JSON.stringify(editedMapping),
          schema_id: schema?.id || "ephemeral",
        });

        const data = await apiFetch(
          `/extract?${params.toString()}`,
          { method: "POST", body: formData },
          instance
        );

        setMapping(editedMapping);
        setResult(data);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    },
    [file, schema, instance]
  );

  // ── Reset ─────────────────────────────────────────────────────

  const handleReset = useCallback(() => {
    setStep(0);
    setSchema(null);
    setFile(null);
    setMapping(null);
    setResult(null);
    setError("");
  }, []);

  // ── Render (no auth or not authenticated) ─────────────────────

  if (AUTH_ENABLED && !isAuthenticated) {
    return (
      <div className="login-screen">
        <h1>Excel Ingestion Portal</h1>
        <p>
          Define what data you want extracted, upload any Excel file, and let AI
          map the columns to your schema.
        </p>
        <button className="btn btn-primary" onClick={handleLogin}>
          Sign in with Microsoft
        </button>
      </div>
    );
  }

  // ── Render (authenticated or auth disabled) ───────────────────

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Excel Ingestion Portal</h1>
        <div className="user-info">
          <span>{userName}</span>
          {AUTH_ENABLED && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleLogout}
            >
              Sign out
            </button>
          )}
        </div>
      </header>

      {/* Stepper */}
      <div className="stepper">
        {STEPS.map((name, i) => (
          <button
            key={name}
            className={`step ${
              i === step ? "active" : i < step ? "completed" : ""
            }`}
            onClick={() => i < step && setStep(i)}
            disabled={i > step}
          >
            {i + 1}. {name}
          </button>
        ))}
      </div>

      {/* Error display */}
      {error && (
        <div className="error-box">
          {error}
          <button
            className="btn btn-sm btn-secondary"
            style={{ marginLeft: "1rem" }}
            onClick={() => setError("")}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Loading overlay */}
      {loading && (
        <div className="loading-overlay">
          <div className="spinner" />
          <span>Processing...</span>
        </div>
      )}

      {/* Step content */}
      {!loading && step === 0 && (
        <div>
          <SchemaLibrary
            apiFetch={(path, opts) => apiFetch(path, opts, instance)}
            onSelect={handleSchemaReady}
          />
          <SchemaEditor initialSchema={schema} onReady={handleSchemaReady} />
        </div>
      )}

      {!loading && step === 1 && <FileUpload onUpload={handleFileUpload} />}

      {!loading && step === 2 && mapping && (
        <MappingView
          mapping={mapping}
          onConfirm={handleConfirmMapping}
          onReExtract={handleReExtract}
        />
      )}

      {!loading && step === 3 && result && (
        <ResultsView result={result} onReset={handleReset} />
      )}
    </div>
  );
}

// ── Root wrapper ────────────────────────────────────────────────

export default function App() {
  if (AUTH_ENABLED && MsalProvider && msalInstance) {
    return (
      <MsalProvider instance={msalInstance}>
        <AppContent />
      </MsalProvider>
    );
  }

  // No auth configured — render directly
  return <AppContent />;
}
