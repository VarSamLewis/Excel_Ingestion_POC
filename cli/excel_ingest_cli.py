#!/usr/bin/env python3

"""Alternative frontend CLI for the Azure-hosted ingestion backend."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import typer

app = typer.Typer(help="Excel ingestion CLI")
schemas_app = typer.Typer(help="Schema library operations")
app.add_typer(schemas_app, name="schemas")


def _backend_url(cli_value: str | None) -> str:
    return (
        cli_value or os.environ.get("BACKEND_URL") or "http://localhost:8000"
    ).rstrip("/")


def _schema_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise typer.BadParameter(f"Failed to parse JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise typer.BadParameter(f"Expected JSON object in {path}")
    return value


def _handle_error(exc: Exception) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text
        typer.echo(f"Request failed: {exc.response.status_code} {body}", err=True)
        raise typer.Exit(1)
    if isinstance(exc, httpx.HTTPError):
        typer.echo(f"HTTP error: {exc}", err=True)
        raise typer.Exit(1)
    raise exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _default_replay_script(
    *, backend_url: str, schema_path: Path, excel_path: Path
) -> str:
    return f"""#!/usr/bin/env python3
import json
from pathlib import Path

import httpx

BACKEND_URL = {backend_url!r}
SCHEMA_PATH = Path({str(schema_path)!r})
EXCEL_PATH = Path({str(excel_path)!r})
OUT_PATH = Path("ingest_output.json")


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    params = {{
        "schema_name": schema["name"],
        "schema_json": json.dumps(schema),
    }}
    files = {{
        "file": (
            EXCEL_PATH.name,
            EXCEL_PATH.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }}
    with httpx.Client(timeout=600.0) as client:
        resp = client.post(f"{{BACKEND_URL}}/ingest", params=params, files=files)
        resp.raise_for_status()
        payload = resp.json()
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {{OUT_PATH}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


@app.command("health")
def health(
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """Check backend health."""
    base = _backend_url(backend_url)
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{base}/health")
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        _handle_error(exc)


@schemas_app.command("list")
def schemas_list(
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """List saved schemas."""
    base = _backend_url(backend_url)
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(f"{base}/schemas")
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        _handle_error(exc)


@schemas_app.command("create")
def schemas_create(
    schema_file: Path = typer.Option(..., exists=True, dir_okay=False),
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """Create schema from JSON file."""
    payload = _load_json(schema_file)
    base = _backend_url(backend_url)
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{base}/schemas", json=payload)
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        _handle_error(exc)


@schemas_app.command("update")
def schemas_update(
    schema_id: str = typer.Option(..., help="Schema ID"),
    schema_file: Path = typer.Option(..., exists=True, dir_okay=False),
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """Update existing schema by ID."""
    payload = _load_json(schema_file)
    base = _backend_url(backend_url)
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.put(f"{base}/schemas/{schema_id}", json=payload)
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        _handle_error(exc)


@schemas_app.command("delete")
def schemas_delete(
    schema_id: str = typer.Option(..., help="Schema ID"),
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """Delete schema by ID."""
    base = _backend_url(backend_url)
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.delete(f"{base}/schemas/{schema_id}")
            resp.raise_for_status()
            typer.echo(json.dumps(resp.json(), indent=2))
    except Exception as exc:
        _handle_error(exc)


@app.command("excel-schema")
def excel_schema(
    excel_file: Path = typer.Option(..., exists=True, dir_okay=False),
    selected_sheets: str | None = typer.Option(
        None, help="Comma-separated sheet names (default all sheets)"
    ),
    out: Path = typer.Option(
        Path("./artifacts/excel_schema.json"), help="Output JSON path"
    ),
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """Request normalized workbook schema from backend."""
    base = _backend_url(backend_url)
    params: dict[str, str] = {}
    if selected_sheets:
        params["selected_sheets"] = selected_sheets

    files = {
        "file": (
            excel_file.name,
            excel_file.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(f"{base}/excel-schema", params=params, files=files)
            resp.raise_for_status()
            payload = resp.json()
        _write_json(out, payload)
        typer.echo(f"Wrote {out}")
        typer.echo(
            f"excel_hash={payload.get('excel_hash')} excel_schema_hash={payload.get('excel_schema_hash')}"
        )
    except Exception as exc:
        _handle_error(exc)


@app.command("ingest")
def ingest(
    schema_file: Path = typer.Option(..., exists=True, dir_okay=False),
    excel_file: Path = typer.Option(..., exists=True, dir_okay=False),
    selected_sheets: str | None = typer.Option(
        None, help="Comma-separated sheet names (default all sheets)"
    ),
    out_dir: Path = typer.Option(Path("./artifacts"), help="Artifact output directory"),
    save_ingest_output: bool = typer.Option(
        False,
        help="Also write ingest_output.json",
    ),
    save_manifest: bool = typer.Option(
        False,
        help="Also write ingest_manifest.json",
    ),
    backend_url: str | None = typer.Option(None, help="Backend base URL"),
) -> None:
    """Run backend ingestion and write JSON artifacts."""
    schema_payload = _load_json(schema_file)
    schema_name = schema_payload.get("name")
    if not isinstance(schema_name, str) or not schema_name:
        raise typer.BadParameter("Schema file must include non-empty top-level 'name'")

    base = _backend_url(backend_url)
    params = {
        "schema_name": schema_name,
        "schema_json": json.dumps(schema_payload),
    }
    if selected_sheets:
        params["selected_sheets"] = selected_sheets

    files = {
        "file": (
            excel_file.name,
            excel_file.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }

    try:
        with httpx.Client(timeout=600.0) as client:
            schema_resp = client.post(
                f"{base}/excel-schema",
                files=files,
                params={"selected_sheets": selected_sheets}
                if selected_sheets
                else None,
            )
            schema_resp.raise_for_status()
            excel_schema_payload = schema_resp.json()

            resp = client.post(f"{base}/ingest", params=params, files=files)
            resp.raise_for_status()
            ingest_payload = resp.json()
    except Exception as exc:
        _handle_error(exc)
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    excel_schema_out = out_dir / "excel_schema.json"
    replay_out = out_dir / "run_ingest.py"
    _write_json(excel_schema_out, excel_schema_payload)

    ingest_out = out_dir / "ingest_output.json"
    if save_ingest_output:
        _write_json(ingest_out, ingest_payload)

    manifest_out = out_dir / "ingest_manifest.json"
    if save_manifest:
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "backend_url": base,
            "excel_file": str(excel_file),
            "schema_file": str(schema_file),
            "excel_hash": ingest_payload.get("excel_hash"),
            "excel_schema_hash": excel_schema_payload.get("excel_schema_hash"),
            "target_schema_hash": _schema_hash(schema_payload),
            "schema_id": ingest_payload.get("schema_id"),
            "schema_version": ingest_payload.get("schema_version"),
        }
        manifest["cache_key"] = (
            f"{manifest['excel_hash']}_{manifest['schema_id']}_{manifest['excel_schema_hash']}_{manifest['target_schema_hash']}"
        )
        _write_json(manifest_out, manifest)
    replay_code = ingest_payload.get("replay_code")
    script_body = (
        replay_code
        if isinstance(replay_code, str) and replay_code.strip()
        else _default_replay_script(
            backend_url=base,
            schema_path=schema_file.resolve(),
            excel_path=excel_file.resolve(),
        )
    )
    replay_out.write_text(script_body, encoding="utf-8")

    row_count = ingest_payload.get("row_count")
    sheets = ingest_payload.get("sheet_names")
    validation_raw = ingest_payload.get("validation")
    validation = validation_raw if isinstance(validation_raw, dict) else {}
    confidence = validation.get("confidence")
    issues_raw = validation.get("issues")
    issues = issues_raw if isinstance(issues_raw, list) else []
    confidence_str = (
        f"{float(confidence):.3f}" if isinstance(confidence, (int, float)) else "n/a"
    )

    typer.echo(
        f"Ingest OK: rows={row_count} sheets={sheets} confidence={confidence_str} issues={len(issues)}"
    )
    typer.echo(f"Wrote {excel_schema_out}")
    typer.echo(f"Wrote {replay_out}")
    if save_ingest_output:
        typer.echo(f"Wrote {ingest_out}")
    if save_manifest:
        typer.echo(f"Wrote {manifest_out}")


if __name__ == "__main__":
    app()
