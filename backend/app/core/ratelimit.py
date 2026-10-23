"""In-process sliding-window rate limiter (login: 10/min per IP).

Good enough for one backend process. If the API is scaled to several processes, move this to PostgreSQL.
"""
import time
from collections import defaultdict, deque

from app.core.config import settings
from app.core.errors import AppError


class SlidingWindowLimiter:
    def __init__(self, limit_per_min: int):
        self.limit = limit_per_min
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.limit:
            raise AppError(429, "RATE_LIMITED", "Too many attempts. Please wait a minute and try again.")
        q.append(now)


login_limiter = SlidingWindowLimiter(settings.login_rate_limit_per_min)
