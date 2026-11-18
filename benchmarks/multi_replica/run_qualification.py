"""Run the bounded two-process multi-replica qualification and write evidence (#206)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Query = Callable[[str, str, Dict[str, Any], Optional[Dict[str, Any]]], Tuple[int, Any]]


def _ensure_repo_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", default="deployment/multi-replica/config")
    parser.add_argument("--out", default="docs/benchmarks/multi-replica.json")
    parser.add_argument("--markdown", default="docs/benchmarks/multi-replica.md")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--check", type=Path, help="Only validate an existing JSON report")
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args(argv)


def _free_ports(count: int) -> List[int]:
    ports: List[int] = []
    for _ in range(count):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            ports.append(int(probe.getsockname()[1]))
    return ports


def _request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return int(response.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {"raw": raw}
        return int(exc.code), parsed


def _wait_ready(host: str, port: int, log_path: Path) -> bool:
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            health, _ = _request("GET", f"http://{host}:{port}/health")
            ready, payload = _request("GET", f"http://{host}:{port}/ready")
            if health == 200 and ready == 200 and payload.get("status") == "ready":
                return True
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    tail = log_path.read_text(encoding="utf-8")[-4000:] if log_path.exists() else ""
    print(f"Replica on port {port} did not become ready:\n{tail}", file=sys.stderr)
    return False


def _start_replica(
    repo_root: Path,
    config_dir: Path,
    workspace: Path,
    store_env: str,
    host: str,
    port: int,
    index: int,
    environ: Dict[str, str],
) -> subprocess.Popen:
    log_path = workspace / f"replica-{index}.log"
    handle = log_path.open("wb")
    env = dict(environ)
    env["GENAI_CONFIG_DIR"] = str(config_dir)
    env["GENAI_QUALIFICATION_STORE"] = store_env
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo_root), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )


def _stop(process: Optional[subprocess.Popen]) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _tenant(tenant: str) -> Dict[str, str]:
    return {"X-Tenant-ID": tenant}


def _poll_experiment(query: Query, exp_id: str, tenant: str) -> Dict[str, Any]:
    deadline = time.time() + 90
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        status, last = query("GET", f"/v1/experiments/{exp_id}", _tenant(tenant))
        if status == 200 and last.get("status") in ("completed", "failed"):
            return last
        time.sleep(0.25)
    return last


def _run_scenario(args: argparse.Namespace, repo_root: Path) -> Dict[str, Any]:
    from core.evaluation.multi_replica import build_report, collect_provenance

    source_config = Path(args.config_dir)
    if not source_config.is_absolute():
        source_config = repo_root / source_config
    workspace = Path(tempfile.mkdtemp(prefix="genai-multi-replica-"))
    config_dir = workspace / "config"
    shutil.copytree(source_config, config_dir)
    store_path = workspace / "store.db"
    os.environ["GENAI_QUALIFICATION_STORE"] = str(store_path)
    (config_dir / "persistence.yaml").write_text(
        "backend: sqlite\npath: ${GENAI_QUALIFICATION_STORE}\nmax_entries: 5000\n",
        encoding="utf-8",
    )
    documents = json.loads((config_dir / "documents.json").read_text(encoding="utf-8"))
    host = args.host
    port_a, port_b = _free_ports(2)
    env = os.environ.copy()
    environ = env
    replica_a: Optional[subprocess.Popen] = None
    replica_b: Optional[subprocess.Popen] = None
    checks: List[Dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def query(method: str, path: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        url = f"http://{host}:{port_a}{path}"
        return _request(method, url, headers, payload)

    def query_b(method: str, path: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        url = f"http://{host}:{port_b}{path}"
        return _request(method, url, headers, payload)

    try:
        from core.services.base_store import build_store

        store = build_store(config_path=str(config_dir / "persistence.yaml"))
        health = store.health()
        record(
            "persistence_secret_reference_resolved",
            health.get("backend") == "sqlite" and str(store_path) in str(health.get("path")),
            f"backend={health.get('backend')} path={health.get('path')}",
        )
        store.close()

        replica_a = _start_replica(
            repo_root, config_dir, workspace, str(store_path), host, port_a, 1, environ
        )
        replica_b = _start_replica(
            repo_root, config_dir, workspace, str(store_path), host, port_b, 2, environ
        )
        ready_a = _wait_ready(host, port_a, workspace / "replica-1.log")
        ready_b = _wait_ready(host, port_b, workspace / "replica-2.log")
        record("both_replicas_ready", ready_a and ready_b, f"A={ready_a} B={ready_b}")
        if not (ready_a and ready_b):
            return build_report(
                checks=checks,
                provenance=collect_provenance(source_config, "sqlite", 2, repo_root=repo_root),
                profile={
                    "topology": "two uvicorn processes, shared SQLite file, single host",
                    "backend": "sqlite",
                    "replicas": 2,
                },
            )

        headers_acme = {**_tenant("acme"), "X-Request-ID": "qual-acme-query"}
        status, acme_result = query(
            "POST", "/v1/query", headers_acme, {"query": "ACME runbook", "top_k": 2}
        )
        acme_request_id = str(acme_result.get("request_id") or "")
        acme_docs = [str(item) for item in acme_result.get("retrieved_docs") or []]
        record(
            "retrieval_acl_tenant_isolation",
            status == 200
            and any("ACME" in doc for doc in acme_docs)
            and not any("Beta" in doc for doc in acme_docs),
            f"status={status} docs={acme_docs}",
        )

        status, beta_result = query_b(
            "POST",
            "/v1/query",
            {**_tenant("beta"), "X-Request-ID": "qual-beta-query"},
            {"query": "Beta research note", "top_k": 2},
        )
        beta_docs = [str(item) for item in beta_result.get("retrieved_docs") or []]
        record(
            "cross_tenant_retrieval_denied",
            status == 200
            and any("Beta" in doc for doc in beta_docs)
            and not any("ACME" in doc for doc in beta_docs),
            f"status={status} docs={beta_docs}",
        )

        status, trace = query_b(
            "GET", f"/v1/traces/{acme_request_id}", _tenant("acme")
        )
        record(
            "trace_visible_on_other_replica",
            status == 200 and bool(trace),
            f"status={status} request_id={acme_request_id}",
        )
        status, _ = query_b("GET", f"/v1/traces/{acme_request_id}", _tenant("beta"))
        record("cross_tenant_trace_denied", status == 404, f"status={status}")

        status, governance = query_b("GET", "/v1/governance/status", _tenant("acme"))
        window = governance.get("window") or {}
        record(
            "spend_visible_on_other_replica",
            status == 200 and int(window.get("requests") or 0) >= 1,
            f"status={status} window={window}",
        )

        status, launch = query(
            "POST",
            "/v1/experiments",
            {**_tenant("acme"), "X-Request-ID": "qual-experiment"},
            {
                "kind": "single",
                "query": "ACME runbook",
                "docs": documents,
                "top_k": 2,
            },
        )
        exp_id = str(launch.get("id") or "")
        experiment = _poll_experiment(query_b, exp_id, "acme") if exp_id else {}
        record(
            "experiment_status_visible_on_other_replica",
            status == 202 and experiment.get("status") == "completed",
            f"launch={status} status={experiment.get('status')}",
        )
        status, _ = query_b("GET", f"/v1/experiments/{exp_id}", _tenant("beta"))
        record("cross_tenant_experiment_denied", status == 404, f"status={status}")

        status, _ = query(
            "POST",
            "/v1/pipeline:rebuild",
            {**_tenant("acme"), "X-Request-ID": "qual-audit"},
            {"overrides": {}},
        )
        status, audit = query_b("GET", "/v1/audit?tenant=acme", _tenant("acme"))
        events = audit.get("events") or []
        record(
            "audit_event_visible_on_other_replica",
            status == 200 and any(event.get("action") == "pipeline_rebuild" for event in events),
            f"status={status} events={len(events)}",
        )

        status, first_hit = query(
            "POST",
            "/v1/query",
            {**_tenant("acme"), "X-Request-ID": "qual-cache-1"},
            {"query": "cache probe", "top_k": 2},
        )
        status_2, second_hit = query(
            "POST",
            "/v1/query",
            {**_tenant("acme"), "X-Request-ID": "qual-cache-2"},
            {"query": "cache probe", "top_k": 2},
        )
        status_3, third_hit = query(
            "POST",
            "/v1/query",
            {**_tenant("beta"), "X-Request-ID": "qual-cache-3"},
            {"query": "cache probe", "top_k": 2},
        )
        record(
            "cache_tenant_key_isolation",
            status == 200
            and status_2 == 200
            and status_3 == 200
            and first_hit.get("cache_hit") is False
            and second_hit.get("cache_hit") is True
            and third_hit.get("cache_hit") is False,
            f"hits={first_hit.get('cache_hit')},{second_hit.get('cache_hit')},{third_hit.get('cache_hit')}",
        )

        _stop(replica_b)
        replica_b = _start_replica(
            repo_root, config_dir, workspace, str(store_path), host, port_b, 2, environ
        )
        restarted = _wait_ready(host, port_b, workspace / "replica-2.log")
        status, trace_after = query_b(
            "GET", f"/v1/traces/{acme_request_id}", _tenant("acme")
        )
        record(
            "restart_recovery",
            restarted and status == 200 and bool(trace_after),
            f"restarted={restarted} status={status}",
        )

        profile = {
            "topology": "two uvicorn processes, shared SQLite file on one host",
            "backend": "sqlite",
            "replicas": 2,
            "store_path": "env:GENAI_QUALIFICATION_STORE",
            "request_pattern": "sequential low-concurrency qualification",
            "identity_mode": "trusted X-Tenant-ID header",
        }
        return build_report(
            checks=checks,
            provenance=collect_provenance(source_config, "sqlite", 2, repo_root=repo_root),
            profile=profile,
        )
    finally:
        _stop(replica_a)
        _stop(replica_b)
        if args.keep_temp:
            print(f"Temporary workspace retained at {workspace}", file=sys.stderr)
        else:
            shutil.rmtree(workspace, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    repo_root = _ensure_repo_path()
    from core.evaluation.multi_replica import check_report, write_report

    args = _parse_args(argv)
    if args.check is not None:
        return 0 if check_report(args.check) else 1
    report = _run_scenario(args, repo_root)
    out = Path(args.out)
    markdown = Path(args.markdown)
    if not out.is_absolute():
        out = repo_root / out
    if not markdown.is_absolute():
        markdown = repo_root / markdown
    write_report(report, out, markdown)
    print(f"status={report['status']} passed={report['summary']['passed']}/{report['summary']['total']}")
    print(f"json={out}")
    print(f"markdown={markdown}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
