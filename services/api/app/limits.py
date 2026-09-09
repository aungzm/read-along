"""Bound upload bodies before multipart parsing can spool them to disk."""

from __future__ import annotations

from collections.abc import Callable

from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadLimitsMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        max_uploads: int,
        has_job_capacity: Callable[[], bool],
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.max_uploads = max_uploads
        self.has_job_capacity = has_job_capacity
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"].rstrip("/") == "/api/jobs"
        ):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        try:
            length = int(headers.get("content-length", "0"))
            if length < 0:
                raise ValueError
        except ValueError:
            await JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)(
                scope, receive, send
            )
            return
        if length > self.max_bytes:
            await self.reject(scope, receive, send)
            return
        if self.active >= self.max_uploads or not self.has_job_capacity():
            await JSONResponse(
                {"detail": "Upload or processing capacity is full. Try again shortly."},
                status_code=429,
                headers={"Retry-After": "5"},
            )(scope, receive, send)
            return

        # No await between checking and incrementing: admission is atomic within
        # this worker's event loop. Deployment limits must account for workers.
        self.active += 1
        received = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    # Starlette closes partially spooled files for this exception.
                    # Its normal 400 response is replaced with 413 below.
                    raise MultiPartException("Upload request is too large.")
            return message

        async def limited_send(message: Message) -> None:
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
            if exceeded:
                await self.reject(scope, receive, send)
        finally:
            self.active -= 1

    async def reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            {"detail": "The upload request is larger than the configured limit."},
            status_code=413,
        )(scope, receive, send)
