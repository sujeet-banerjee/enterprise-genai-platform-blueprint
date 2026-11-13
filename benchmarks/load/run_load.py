"""Reference load/latency harness CLI (issue #197, Workstream K / showcase H5).

Boots the API with a known-good config (dummy providers by default) and runs a
bounded load plan across concurrency levels, plus the batch endpoint. Writes a
provenance-stamped JSON + Markdown report.

Examples::

    # In-process (fast; used by tests/CI): dummy providers, no port binding.
    python benchmarks/load/run_load.py --in-process \\
        --config-dir deployment/smoke/config --requests 5 --concurrency 1

    # Real server (reference numbers): boots uvicorn and drives it over HTTP.
    python benchmarks/load/run_load.py --config-dir deployment/smoke/config \\
        --concurrency 1,4,8,16 --requests 50 \\
        --out docs/benchmarks/load.json --markdown docs/benchmarks/load.md

    # Attach to an already-running API instead of booting one.
    python benchmarks/load/run_load.py --base-url http://localhost:8000

Exit codes: 0 success, 1 runtime failure, 2 invalid configuration.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.evaluation.load_harness import (  # noqa: E402
    DEFAULT_SCENARIOS,
    LoadHarnessError,
    LoadScenario,
    build_report,
    expand_plan,
    write_report,
)

DEFAULT_CONFIG_DIR = "deployment/smoke/config"

_CONFIG_FILES = {
    "models_config_path": "models.yaml",
    "prompt_config_path": "prompt_config.yaml",
    "retrieval_config_path": "retrieval.yaml",
    "governance_config_path": "governance.yaml",
    "observability_config_path": "observability.yaml",
    "api_config_path": "api.yaml",
    "audit_config_path": "audit.yaml",
    "access_control_config_path": "access_control.yaml",
    "resilience_config_path": "resilience.yaml",
    "guardrails_config_path": "guardrails.yaml",
    "tenants_config_path": "tenants.yaml",
    "identity_config_path": "identity.yaml",
    "attribution_config_path": "attribution.yaml",
    "acl_config_path": "acl.yaml",
    "persistence_config_path": "persistence.yaml",
}


def config_paths(config_dir: str | Path) -> Dict[str, str]:
    """Map ``create_app`` keyword names to existing files under ``config_dir``."""
    base = Path(config_dir)
    return {
        name: str(base / filename)
        for name, filename in _CONFIG_FILES.items()
        if (base / filename).exists()
    }


class _SharedClient:
    """Adapter so a shared in-process client is never closed between runs."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def request(self, method: str, url: str, json: Any = None) -> Any:
        return self._client.request(method, url, json=json)


@contextlib.contextmanager
def serve(config_dir: str | Path, host: str, port: int, startup_timeout: float = 60.0) -> Iterator[str]:
    """Boot uvicorn on a bound socket and yield the base URL."""
    import uvicorn

    from app.main import create_app

    application = create_app(**config_paths(config_dir))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    actual_port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, log_level="warning"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    deadline = time.time() + startup_timeout
    while not server.started and time.time() < deadline:
        if not thread.is_alive():  # pragma: no cover - startup failure path
            raise RuntimeError("uvicorn failed to start")
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - startup timeout path
        raise RuntimeError("uvicorn startup timed out")
    try:
        yield f"http://{host}:{actual_port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        with contextlib.suppress(OSError):
            sock.close()


@contextlib.contextmanager
def client_source(
    args: argparse.Namespace,
) -> Iterator[Tuple[Callable[[], Any], str]]:
    """Yield ``(client_factory, base_url)`` for the selected transport."""
    if args.base_url:
        import httpx

        def factory() -> Any:
            return httpx.Client(base_url=args.base_url, timeout=args.timeout)

        yield factory, args.base_url
        return

    if args.in_process:
        from fastapi.testclient import TestClient

        from app.main import create_app

        application = create_app(**config_paths(args.config_dir))
        with TestClient(application) as client:

            def factory() -> Any:
                return _SharedClient(client)

            yield factory, ""
        return

    with serve(args.config_dir, args.host, args.port) as base_url:
        import httpx

        def factory() -> Any:
            return httpx.Client(base_url=base_url, timeout=args.timeout)

        yield factory, base_url


def _parse_ints(value: str) -> List[int]:
    try:
        return [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise LoadHarnessError(f"invalid integer list: {value!r}") from exc


def _select_scenarios(names: Sequence[str]) -> List[LoadScenario]:
    if not names:
        return list(DEFAULT_SCENARIOS)
    by_name = {scenario.name: scenario for scenario in DEFAULT_SCENARIOS}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        available = ", ".join(sorted(by_name))
        raise LoadHarnessError(
            f"unknown scenario(s): {', '.join(unknown)}; available: {available}"
        )
    return [by_name[name] for name in names]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python benchmarks/load/run_load.py",
        description="Run a bounded reference load/latency plan against the API.",
    )
    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR)
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="use an in-process TestClient instead of booting uvicorn",
    )
    parser.add_argument("--base-url", help="drive an already-running API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--concurrency", default="1,4,8,16", help="comma-separated concurrency levels"
    )
    parser.add_argument("--requests", type=int, default=50, help="requests per run")
    parser.add_argument("--warmup", type=int, default=2, help="uncounted warmup requests")
    parser.add_argument(
        "--scenarios",
        default="health,ready,query,batch",
        help="comma-separated scenario names (default: all)",
    )
    parser.add_argument("--out", help="write the JSON report here")
    parser.add_argument("--markdown", help="write the Markdown report here")
    parser.add_argument("--json", action="store_true", help="print the JSON report")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.in_process and args.base_url:
        parser.error("--in-process and --base-url are mutually exclusive")

    try:
        concurrencies = _parse_ints(args.concurrency)
        scenarios = _select_scenarios(
            [part.strip() for part in args.scenarios.split(",") if part.strip()]
        )
        # Validate the plan before booting anything (fail fast on bad config).
        expand_plan(scenarios, concurrencies, args.requests)
        with client_source(args) as (factory, base_url):
            report = build_report(
                scenarios,
                concurrencies=concurrencies,
                requests_per_scenario=args.requests,
                warmup=args.warmup,
                client_factory=factory,
                base_url=base_url,
                config_dir=args.config_dir,
            )
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        if args.markdown:
            Path(args.markdown).parent.mkdir(parents=True, exist_ok=True)
        write_report(report, out=args.out, markdown=args.markdown)
    except LoadHarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - runtime failure path
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        summary = report.get("summary") or {}
        print(
            f"load report: runs={summary.get('runs')} "
            f"requests={summary.get('total_requests')} "
            f"errors={summary.get('total_errors')} "
            f"error_rate={float(summary.get('error_rate') or 0.0):.4f}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
