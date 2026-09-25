from fastapi import APIRouter, HTTPException, Query, Response, status
from starlette.requests import Request

from kinetiq.core.queue_engine import QueueEngine
from kinetiq.core.storage import QueueAlreadyExistsError, QueueNotFoundError
from kinetiq.models import (
    CreateQueueRequest,
    DeleteMessageRequest,
    Message,
    QueueResponse,
    SendMessageRequest,
    SendMessageResponse,
)

router = APIRouter(tags=["queues"])


def _engine(request: Request) -> QueueEngine:
    return request.app.state.queue_engine


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, QueueNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, QueueAlreadyExistsError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    raise error


@router.post(
    "/queues",
    operation_id="create_queue",
    response_model=QueueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_queue(payload: CreateQueueRequest, request: Request) -> QueueResponse:
    try:
        return await _engine(request).create_queue(payload)
    except (QueueNotFoundError, QueueAlreadyExistsError) as error:
        _raise_http_error(error)


@router.post(
    "/queues/{queue_name}/messages",
    operation_id="send_message",
    response_model=SendMessageResponse,
)
async def send_message(
    queue_name: str, payload: SendMessageRequest, request: Request
) -> SendMessageResponse:
    try:
        return await _engine(request).send_message(queue_name, payload)
    except QueueNotFoundError as error:
        _raise_http_error(error)


@router.get(
    "/queues/{queue_name}/messages",
    operation_id="receive_messages",
    response_model=list[Message],
)
async def receive_messages(
    queue_name: str,
    request: Request,
    max_messages: int = Query(default=1, ge=1, le=10),
    visibility_timeout: int | None = Query(default=None, ge=0),
    wait_time_seconds: int = Query(default=0, ge=0, le=20),
) -> list[Message]:
    try:
        return await _engine(request).receive_messages(
            queue_name,
            max_messages,
            visibility_timeout,
            wait_time_seconds,
        )
    except QueueNotFoundError as error:
        _raise_http_error(error)


@router.delete(
    "/queues/{queue_name}/messages",
    operation_id="delete_message",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_message(
    queue_name: str, payload: DeleteMessageRequest, request: Request
) -> Response:
    try:
        deleted = await _engine(request).delete_message(
            queue_name, payload.receipt_handle
        )
    except QueueNotFoundError as error:
        _raise_http_error(error)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid receipt handle or message lease expired",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)