"""In-process pub/sub for live memory updates (SSE)."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from uuid import UUID

_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(user_id: UUID) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[str(user_id)].append(queue)
    return queue


def unsubscribe(user_id: UUID, queue: asyncio.Queue) -> None:
    key = str(user_id)
    if queue in _subscribers.get(key, []):
        _subscribers[key].remove(queue)
    if key in _subscribers and not _subscribers[key]:
        del _subscribers[key]


def publish(user_id: UUID, payload: dict[str, Any]) -> None:
    key = str(user_id)
    for queue in list(_subscribers.get(key, [])):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass
