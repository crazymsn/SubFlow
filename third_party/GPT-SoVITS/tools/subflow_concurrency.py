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


class _PrefetchedStream:
    def __init__(self, first, iterator):
        self.first = first
        self.iterator = iterator
        self.started = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.started:
            self.started = True
            return self.first
        return await anext(self.iterator)

    async def aclose(self):
        await self.iterator.aclose()


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

    async def open_stream(self, factory):
        iterator = self.stream(factory)
        try:
            first = await anext(iterator)
        except BaseException as exc:
            with anyio.CancelScope(shield=True):
                await iterator.aclose()
            if isinstance(exc, StopAsyncIteration):
                raise ValueError("Synthesis produced no audio chunks") from exc
            raise
        return _PrefetchedStream(first, iterator)

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
