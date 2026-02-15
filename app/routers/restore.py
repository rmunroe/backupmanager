from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel
from app.auth import require_auth
from app.services.server_service import get_server_service
from app.services.backup_service import get_backup_service
from app.services.restore_service import get_restore_service, RestoreStep

router = APIRouter()


class RestoreRequest(BaseModel):
    backup: str


@router.post("/api/servers/{server_name}/restore")
async def initiate_restore(
    server_name: str,
    request: RestoreRequest,
    background_tasks: BackgroundTasks,
    _=Depends(require_auth),
):
    """Initiate a backup restore."""
    server_service = get_server_service()
    backup_service = get_backup_service()
    restore_service = get_restore_service()

    # Validate server
    if not server_service.is_valid_server(server_name):
        raise HTTPException(status_code=404, detail="Server not found")

    # Validate backup
    if not backup_service.backup_exists(server_name, request.backup):
        raise HTTPException(status_code=404, detail="Backup not found")

    # Create restore job
    job = restore_service.create_job(server_name, request.backup)
    if not job:
        raise HTTPException(
            status_code=409, detail="A restore is already in progress for this server"
        )

    # Start restore in background
    background_tasks.add_task(restore_service.execute_restore, job.id)

    return {"job_id": job.id, "status": "started"}


@router.get("/api/restore/{job_id}/status")
async def get_restore_status(job_id: str, _=Depends(require_auth)):
    """Get the status of a restore job."""
    restore_service = get_restore_service()
    job = restore_service.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.id,
        "server_name": job.server_name,
        "backup_file": job.backup_file,
        "step": job.step.value,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "started_at": job.started_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.websocket("/ws/restore/{job_id}")
async def restore_progress_ws(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time restore progress."""
    await websocket.accept()

    restore_service = get_restore_service()
    job = restore_service.get_job(job_id)

    if not job:
        await websocket.close(code=4004, reason="Job not found")
        return

    # Send current status immediately
    await websocket.send_json(
        {
            "job_id": job.id,
            "step": job.step.value,
            "progress": job.progress,
            "message": job.message,
            "error": job.error,
        }
    )

    # If already complete, close the connection
    if job.step in (RestoreStep.COMPLETED, RestoreStep.FAILED):
        await websocket.close()
        return

    # Register callback for progress updates
    async def send_progress(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    restore_service.register_progress_callback(job_id, send_progress)

    try:
        # Keep connection alive until job completes or client disconnects
        while True:
            try:
                # Wait for messages (ping/pong or close)
                await websocket.receive_text()
            except WebSocketDisconnect:
                break

            # Check if job is done
            job = restore_service.get_job(job_id)
            if job and job.step in (RestoreStep.COMPLETED, RestoreStep.FAILED):
                break
    finally:
        restore_service.unregister_progress_callback(job_id)
        try:
            await websocket.close()
        except Exception:
            pass
