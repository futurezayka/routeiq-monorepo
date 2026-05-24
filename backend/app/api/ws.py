import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time vehicle position updates."""
    manager = getattr(websocket.app.state, "ws_manager", None)
    if manager is None:
        await websocket.accept()
        await websocket.close(code=1011)
        return
    await manager.accept_and_connect(
        websocket, ["positions", "incidents", "route-updates"],
    )
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=60.0,
                )
            except TimeoutError:
                break
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
