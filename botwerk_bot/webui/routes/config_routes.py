"""Admin config management API routes."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from botwerk_bot.webui.schemas import TokenPayload

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path.home() / ".botwerk" / "config" / "config.json"

# Keys whose values should be masked in GET responses.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(token|secret|key|password|api_key)"),
)
_MASK = "********"


def _is_secret_key(key: str) -> bool:
    """Return True if the key name looks like a secret."""
    return any(p.search(key) for p in _SECRET_PATTERNS)


def _sanitize(obj: object, *, depth: int = 0) -> object:
    """Recursively mask secret-looking values in a JSON-like structure."""
    if depth > 20:
        return obj
    if isinstance(obj, dict):
        return {
            k: (_MASK if _is_secret_key(k) and isinstance(v, str) and v else _sanitize(v, depth=depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize(item, depth=depth + 1) for item in obj]
    return obj


def _get_config_path() -> Path:
    """Return the config file path (mockable in tests)."""
    return _DEFAULT_CONFIG_PATH


def create_config_router(auth_dep: object) -> APIRouter:
    """Build and return the admin config router."""
    router = APIRouter(prefix="/admin/config", tags=["admin-config"])

    def _require_admin(token: TokenPayload) -> None:
        if not token.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )

    @router.get("")
    async def get_config(
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Return the current config.json with secrets masked."""
        _require_admin(token)

        config_path = _get_config_path()
        if not config_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Config file not found",
            )

        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read config: {exc}",
            ) from exc

        return {"config": _sanitize(raw)}

    @router.put("")
    async def update_config(
        body: dict,
        token: TokenPayload = Depends(auth_dep),
    ) -> dict:
        """Update config.json with the provided key-value pairs.

        Accepts a JSON object. Keys are merged into the existing config.
        Values set to ``null`` remove the key. Nested objects are deep-merged.
        """
        _require_admin(token)

        config_path = _get_config_path()
        if not config_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Config file not found",
            )

        # Reject masked values to prevent accidental secret overwrites.
        def _check_no_masks(obj: object, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _check_no_masks(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    _check_no_masks(v, f"{path}[{i}]")
            elif obj == _MASK:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Masked value at {path} — provide the real value or omit the key",
                )

        _check_no_masks(body)

        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read config: {exc}",
            ) from exc

        # Deep-merge updates into existing config.
        def _deep_merge(base: dict, updates: dict) -> dict:
            result = dict(base)
            for k, v in updates.items():
                if v is None:
                    result.pop(k, None)
                elif isinstance(v, dict) and isinstance(result.get(k), dict):
                    result[k] = _deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        merged = _deep_merge(existing, body)

        # Validate by trying to parse as AgentConfig.
        try:
            from botwerk_bot.config import AgentConfig
            AgentConfig(**merged)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid config: {exc}",
            ) from exc

        # Write atomically.
        try:
            from botwerk_bot.infra.json_store import atomic_json_save
            atomic_json_save(config_path, merged)
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write config: {exc}",
            ) from exc

        logger.info("Config updated by user_id=%d", token.user_id)
        return {"status": "ok", "config": _sanitize(merged)}

    return router
