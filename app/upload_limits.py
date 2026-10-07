"""ASGI request-body admission before multipart files reach temporary storage."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse


class UploadBodyLimit:
    def __init__(self, app, *, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") != "/api/jobs":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > self.limit():
            response = JSONResponse({"detail": "上傳內容超過大小限制"}, status_code=413)
            return await response(scope, receive, send)
        consumed = 0
        response_started = False

        async def limited_receive():
            nonlocal consumed
            event = await receive()
            if event["type"] == "http.request":
                consumed += len(event.get("body", b""))
                if consumed > self.limit():
                    raise HTTPException(413, "上傳內容超過大小限制")
            return event

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except HTTPException as exc:
            if response_started:
                raise
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            await response(scope, receive, send)
