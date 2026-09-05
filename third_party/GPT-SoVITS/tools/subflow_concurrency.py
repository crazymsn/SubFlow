"""Keep model operations serialized without blocking the HTTP event loop."""
from __future__ import annotations

import asyncio
from contextlib import suppress

import anyio
from starlette.responses import StreamingResponse


class ModelStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Starlette cancellation can happen while sending a yielded chunk,
            # outside the iterator itself. Close it before the response exits.
            with anyio.CancelScope(shield=True):
                await self.body_iterator.aclose()


async def _worker(operation):
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A disconnected client cannot cancel a Python inference thread. Keep
        # ownership until it finishes so the next request cannot mutate its model.
        with anyio.CancelScope(shield=True):
            while not task.done():
                with suppress(BaseException):
                    await asyncio.shield(task)
            with suppress(BaseException):
                task.result()
        raise


class SerializedModel:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def call(self, operation):
        async with self.lock:
            return await _worker(operation)

    async def stream(self, factory):
        async with self.lock:
            iterator = factory()
            sentinel = object()
            try:
                while True:
                    chunk = await _worker(lambda: next(iterator, sentinel))
                    if chunk is sentinel:
                        break
                    yield chunk
            finally:
                with anyio.CancelScope(shield=True):
                    await _worker(iterator.close)
