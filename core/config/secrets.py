"""Secret reference resolution (issue #46, workstream E3).

Config files never contain secrets. Instead they reference environment-variable
backed secrets with either syntax:

- ``${ENV_VAR}`` - shell-style interpolation,
- ``env:ENV_VAR`` - explicit scheme prefix.

Resolution happens **at load time** and the resolved values are kept in memory
only; the introspection layer runs every config through
``SensitiveDataRedactor`` before it leaves the process, so a resolved secret is
never emitted by ``/v1/config``, traces or logs.

A missing referenced secret is a hard error (:class:`SecretResolutionError`) so
misconfiguration fails fast instead of silently sending an empty key upstream.

Production paths (Vault / Kubernetes secrets) inject the value into the process
environment before start-up (e.g. via the Vault Agent Injector or a
``secretKeyRef`` env var), so the same ``${ENV_VAR}`` mechanism works unchanged.
"""

import os
import re
from typing import Any, Dict, Iterable, Optional

__all__ = [
    "SecretResolutionError",
    "resolve_secrets",
    "find_secret_refs",
    "SECRET_REF_SCHEME",
]

SECRET_REF_SCHEME = "env:"

# ${VAR} - shell-style. Conservative name charset so unrelated "${...}" usage
# (e.g. prompt templates) is not accidentally rewritten.
_BRACE_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# env:VAR - explicit scheme.
_SCHEME_REF = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")


class SecretResolutionError(RuntimeError):
    """Raised when a referenced secret is not present in the environment."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"Secret reference '{name}' could not be resolved: environment "
            f"variable is not set. Provide it via the environment (locally in "
            f".env, in production via Vault / a Kubernetes secretKeyRef)."
        )


def find_secret_refs(value: Any) -> Iterable[str]:
    """Yield every environment-variable name referenced in ``value``."""
    if isinstance(value, str):
        for match in _BRACE_REF.finditer(value):
            yield match.group(1)
        scheme = _SCHEME_REF.match(value)
        if scheme:
            yield scheme.group(1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from find_secret_refs(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from find_secret_refs(item)


def _resolve_str(text: str, environ: Dict[str, str]) -> str:
    """Resolve a single string, raising on any unresolved reference."""
    scheme = _SCHEME_REF.match(text)
    if scheme:
        name = scheme.group(1)
        if name not in environ:
            raise SecretResolutionError(name)
        return environ[name]

    if "${" not in text:
        return text

    def _sub(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in environ:
            raise SecretResolutionError(name)
        return environ[name]

    return _BRACE_REF.sub(_sub, text)


def resolve_secrets(
    config: Any,
    environ: Optional[Dict[str, str]] = None,
) -> Any:
    """Recursively resolve secret references in a loaded config mapping.

    Only values are rewritten; dict keys are left untouched. Returns a new
    structure (the input is not mutated).
    """
    env = dict(os.environ) if environ is None else environ
    if isinstance(config, str):
        return _resolve_str(config, env)
    if isinstance(config, dict):
        return {k: resolve_secrets(v, env) for k, v in config.items()}
    if isinstance(config, list):
        return [resolve_secrets(item, env) for item in config]
    if isinstance(config, tuple):
        return tuple(resolve_secrets(item, env) for item in config)
    return config
