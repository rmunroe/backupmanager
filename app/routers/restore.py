import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth import require_auth
from app.services.server_service import get_server_service
from app.services.backup_service import get_backup_service
from app.services.restore_service import get_restore_service

logger = logging.getLogger(__name__)
router = APIRouter()


class RestoreRequest(BaseModel):
    backup: str


@router.post("/api/servers/{server_name}/restore")
async def initiate_restore(
    server_name: str,
    request: RestoreRequest,
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

    # Start restore in background thread (fire and forget)
    logger.info(f"Starting restore job {job.id} for {server_name}")
    restore_service.start_restore(job.id)

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
