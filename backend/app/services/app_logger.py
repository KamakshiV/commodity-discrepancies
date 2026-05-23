"""Structured application logging — stdout + request-scoped buffer for API responses."""

from __future__ import annotations

import logging
import time
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import List, Optional

from app.models.schemas import ApplicationLogEntry

logger = logging.getLogger("commodity.analysis")

_request_logs: ContextVar[Optional[List[ApplicationLogEntry]]] = ContextVar(
    "request_logs", default=None
)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("commodity")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(handler)
    root.setLevel(level)


def begin_analysis_logs() -> None:
    _request_logs.set([])


def collect_logs() -> List[ApplicationLogEntry]:
    logs = _request_logs.get()
    return list(logs) if logs else []


def _emit(entry: ApplicationLogEntry) -> None:
    buf = _request_logs.get()
    if buf is not None:
        buf.append(entry)

    parts = [f"[{entry.stage}] {entry.message}"]
    if entry.agent_name:
        parts.append(f"agent={entry.agent_name}")
    if entry.model:
        parts.append(f"model={entry.model}")
    if entry.prompt_tokens is not None:
        parts.append(f"prompt_tokens={entry.prompt_tokens}")
    if entry.completion_tokens is not None:
        parts.append(f"completion_tokens={entry.completion_tokens}")
    if entry.total_tokens is not None:
        parts.append(f"total_tokens={entry.total_tokens}")
    if entry.duration_ms is not None:
        parts.append(f"duration_ms={entry.duration_ms:.0f}")

    log_fn = logger.info
    if entry.level == "warning":
        log_fn = logger.warning
    elif entry.level == "error":
        log_fn = logger.error
    elif entry.level == "ai":
        log_fn = logger.info

    log_fn(" | ".join(parts))
    if entry.detail:
        logger.debug(entry.detail)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_info(
    stage: str,
    message: str,
    *,
    detail: Optional[str] = None,
    duration_ms: Optional[float] = None,
) -> None:
    _emit(
        ApplicationLogEntry(
            timestamp=_now_iso(),
            stage=stage,
            level="info",
            message=message,
            detail=detail,
            duration_ms=duration_ms,
        )
    )


def log_success(
    stage: str,
    message: str,
    *,
    detail: Optional[str] = None,
    duration_ms: Optional[float] = None,
) -> None:
    _emit(
        ApplicationLogEntry(
            timestamp=_now_iso(),
            stage=stage,
            level="success",
            message=message,
            detail=detail,
            duration_ms=duration_ms,
        )
    )


def log_warning(
    stage: str,
    message: str,
    *,
    detail: Optional[str] = None,
    duration_ms: Optional[float] = None,
) -> None:
    _emit(
        ApplicationLogEntry(
            timestamp=_now_iso(),
            stage=stage,
            level="warning",
            message=message,
            detail=detail,
            duration_ms=duration_ms,
        )
    )


def log_error(
    stage: str,
    message: str,
    *,
    detail: Optional[str] = None,
    duration_ms: Optional[float] = None,
    exc: Optional[BaseException] = None,
) -> None:
    detail_text = detail
    if exc is not None and not detail_text:
        detail_text = traceback.format_exc()
    _emit(
        ApplicationLogEntry(
            timestamp=_now_iso(),
            stage=stage,
            level="error",
            message=message,
            detail=detail_text,
            duration_ms=duration_ms,
        )
    )


def log_ai_agent_start(
    agent_name: str,
    model: str,
    *,
    system_prompt_chars: int,
    user_prompt_chars: int,
) -> None:
    _emit(
        ApplicationLogEntry(
            timestamp=_now_iso(),
            stage="ai_agent",
            level="ai",
            message=f"AI agent started: {agent_name}",
            agent_name=agent_name,
            model=model,
            detail=(
                f"system_chars={system_prompt_chars}, "
                f"user_chars={user_prompt_chars}, "
                f"total_input_chars={system_prompt_chars + user_prompt_chars}"
            ),
        )
    )


def log_ai_agent_finish(
    agent_name: str,
    model: str,
    *,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    total_tokens: Optional[int],
    duration_ms: float,
    response_chars: int,
) -> None:
    _emit(
        ApplicationLogEntry(
            timestamp=_now_iso(),
            stage="ai_agent",
            level="ai",
            message=f"AI agent finished: {agent_name}",
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            detail=f"response_chars={response_chars}",
        )
    )


class StageTimer:
    """Context manager that logs stage start/finish with elapsed time."""

    def __init__(self, stage: str, start_message: str, finish_message: str):
        self.stage = stage
        self.start_message = start_message
        self.finish_message = finish_message
        self._start = 0.0

    def __enter__(self) -> "StageTimer":
        self._start = time.perf_counter()
        log_info(self.stage, self.start_message)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ms = (time.perf_counter() - self._start) * 1000
        if exc_type:
            log_error(
                self.stage,
                f"{self.finish_message} failed: {exc}",
                duration_ms=ms,
                exc=exc if isinstance(exc, BaseException) else None,
            )
        else:
            log_success(self.stage, self.finish_message, duration_ms=ms)
        return False
