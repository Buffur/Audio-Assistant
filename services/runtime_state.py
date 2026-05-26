import time
from typing import Any


MAX_ERROR_MESSAGE_LENGTH = 500
RUNTIME_WARNING_WINDOW_SECONDS = 5 * 60

_runtime_errors: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def _truncate(value: str, max_length: int = MAX_ERROR_MESSAGE_LENGTH) -> str:
    if len(value) <= max_length:
        return value

    return value[: max_length - 3] + "..."


def record_runtime_error(
    component: str,
    error: Exception,
    *,
    now: float | None = None,
) -> None:
    component = component.strip() or "unknown"
    current_time = _now() if now is None else now

    entry = _runtime_errors.setdefault(
        component,
        {
            "component": component,
            "error_count": 0,
            "first_seen_at": current_time,
        },
    )

    entry["error_count"] = int(entry.get("error_count") or 0) + 1
    entry["last_seen_at"] = current_time
    entry["last_error_type"] = type(error).__name__
    entry["last_error_message"] = _truncate(str(error))


def reset_runtime_state() -> None:
    _runtime_errors.clear()


def get_runtime_health(
    *,
    now: float | None = None,
    warning_window_seconds: int = RUNTIME_WARNING_WINDOW_SECONDS,
) -> dict[str, Any]:
    current_time = _now() if now is None else now
    components = []
    degraded = False

    for entry in sorted(
        _runtime_errors.values(),
        key=lambda item: str(item.get("component") or ""),
    ):
        last_seen_at = float(entry.get("last_seen_at") or 0)
        seconds_since_last_error = max(current_time - last_seen_at, 0)

        component = dict(entry)
        component["seconds_since_last_error"] = round(seconds_since_last_error, 3)
        components.append(component)

        if seconds_since_last_error <= warning_window_seconds:
            degraded = True

    return {
        "status": "degraded" if degraded else "ok",
        "warning_window_seconds": warning_window_seconds,
        "components": components,
    }
