"""Shared API dependencies: sessions, the dev user, and rate limiting (§7)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import repo
from app.db.session import get_sessionmaker


async def db_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def current_user_id(session: AsyncSession = Depends(db_session)) -> str:
    """Single-tenant dev identity.

    Authentication is out of scope for this build; every request is the configured dev
    user. The user_id threads through the whole stack (assets, documents, the cost
    ledger), so adding real auth means replacing this one function.
    """
    return await repo.ensure_user(session, get_settings().dev_user_email)


class RateLimiter:
    """§7: per-user and per-IP rate limits. Generation and decomposition are both
    GPU-expensive and attractive to abuse."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: float = 3600.0) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry_after = int(window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"rate limit reached ({limit}/hour); retry in {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)


_limiter = RateLimiter()


def rate_limit_generation(request: Request) -> None:
    settings = get_settings()
    client = request.client.host if request.client else "unknown"
    _limiter.check(f"gen:{client}", settings.rate_limit_generations_per_hour)


async def check_budget(session: AsyncSession, user_id: str) -> None:
    """§6.7: per-user daily ceiling. Degrade rather than error where possible, but a
    hard stop is better than an unbounded bill."""
    settings = get_settings()
    usage = await repo.usage_today(session, user_id)
    if usage["costCents"] >= settings.max_cost_cents_per_user_per_day:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail=(f"daily generation budget reached "
                    f"({usage['costCents']}c of "
                    f"{settings.max_cost_cents_per_user_per_day}c)"),
        )
