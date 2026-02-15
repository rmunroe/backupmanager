import asyncio
import uuid
import shutil
import tarfile
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Dict, Callable, Awaitable
from dataclasses import dataclass, field
from app.config import get_settings
from app.services.docker_service import get_docker_service


class RestoreStep(str, Enum):
    PENDING = "pending"
    STOPPING = "stopping"
    CLEARING = "clearing"
    EXTRACTING = "extracting"
    STARTING = "starting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RestoreJob:
    id: str
    server_name: str
    backup_file: str
    step: RestoreStep = RestoreStep.PENDING
    progress: int = 0  # 0-100
    message: str = ""
    error: str | None = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    container_was_running: bool = False


class RestoreService:
    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self.base_path = Path(base_path or settings.servers_base_path)
        self.docker = get_docker_service()
        self.jobs: Dict[str, RestoreJob] = {}
        self._progress_callbacks: Dict[str, Callable[[dict], Awaitable[None]]] = {}
        self._active_restores: Dict[str, str] = {}  # server_name -> job_id

    def create_job(self, server_name: str, backup_file: str) -> RestoreJob | None:
        """Create a new restore job. Returns None if restore already in progress."""
        # Check for active restore on this server
        if server_name in self._active_restores:
            existing_job = self.jobs.get(self._active_restores[server_name])
            if existing_job and existing_job.step not in (
                RestoreStep.COMPLETED,
                RestoreStep.FAILED,
            ):
                return None

        job_id = str(uuid.uuid4())[:8]
        job = RestoreJob(
            id=job_id,
            server_name=server_name,
            backup_file=backup_file,
        )
        self.jobs[job_id] = job
        self._active_restores[server_name] = job_id
        return job

    def get_job(self, job_id: str) -> RestoreJob | None:
        return self.jobs.get(job_id)

    async def execute_restore(self, job_id: str) -> bool:
        """Execute restore operation asynchronously."""
        job = self.jobs.get(job_id)
        if not job:
            return False

        server_path = self.base_path / job.server_name
        data_dir = server_path / "data"
        backup_path = server_path / "backups" / job.backup_file

        try:
            # Step 1: Check container status
            await self._update_job(
                job, RestoreStep.STOPPING, 5, "Checking container status..."
            )

            is_running = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.docker.is_running(job.server_name)
            )

            if is_running:
                job.container_was_running = True
                await self._update_job(
                    job, RestoreStep.STOPPING, 10, "Stopping container..."
                )

                success, msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.docker.stop_container(job.server_name, timeout=60)
                )

                if not success:
                    raise Exception(f"Failed to stop container: {msg}")

                await self._update_job(
                    job, RestoreStep.STOPPING, 25, "Container stopped"
                )
            else:
                job.container_was_running = False
                await self._update_job(
                    job, RestoreStep.STOPPING, 25, "Container not running"
                )

            # Step 2: Clear data directory
            await self._update_job(
                job, RestoreStep.CLEARING, 30, "Removing old data..."
            )

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: shutil.rmtree(data_dir, ignore_errors=True)
            )

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: data_dir.mkdir(parents=True, exist_ok=True)
            )

            await self._update_job(
                job, RestoreStep.CLEARING, 40, "Data directory cleared"
            )

            # Step 3: Extract backup
            await self._update_job(
                job, RestoreStep.EXTRACTING, 45, "Extracting backup..."
            )

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._extract_backup(backup_path, data_dir)
            )

            await self._update_job(
                job, RestoreStep.EXTRACTING, 85, "Backup extracted"
            )

            # Step 4: Restart container if it was running
            if job.container_was_running:
                await self._update_job(
                    job, RestoreStep.STARTING, 90, "Starting container..."
                )

                success, msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.docker.start_container(job.server_name)
                )

                if not success:
                    raise Exception(f"Failed to start container: {msg}")

                await self._update_job(
                    job, RestoreStep.STARTING, 95, "Container started"
                )
            else:
                await self._update_job(
                    job, RestoreStep.STARTING, 95, "Container left stopped (was not running before)"
                )

            # Complete
            job.completed_at = datetime.now()
            await self._update_job(
                job, RestoreStep.COMPLETED, 100, "Restore completed successfully!"
            )
            return True

        except Exception as e:
            job.error = str(e)
            job.completed_at = datetime.now()
            await self._update_job(
                job, RestoreStep.FAILED, job.progress, f"Error: {str(e)}"
            )
            return False
        finally:
            # Clean up active restore tracking
            if self._active_restores.get(job.server_name) == job_id:
                del self._active_restores[job.server_name]

    def _extract_backup(self, backup_path: Path, data_dir: Path):
        """Extract tarball to data directory."""
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(path=data_dir)

    async def _update_job(
        self, job: RestoreJob, step: RestoreStep, progress: int, message: str
    ):
        """Update job status and notify listeners."""
        job.step = step
        job.progress = progress
        job.message = message

        # Notify WebSocket listeners
        callback = self._progress_callbacks.get(job.id)
        if callback:
            try:
                await callback(
                    {
                        "job_id": job.id,
                        "step": step.value,
                        "progress": progress,
                        "message": message,
                        "error": job.error,
                    }
                )
            except Exception:
                # Ignore callback errors
                pass

    def register_progress_callback(
        self, job_id: str, callback: Callable[[dict], Awaitable[None]]
    ):
        self._progress_callbacks[job_id] = callback

    def unregister_progress_callback(self, job_id: str):
        self._progress_callbacks.pop(job_id, None)


# Singleton instance
_restore_service: RestoreService | None = None


def get_restore_service() -> RestoreService:
    global _restore_service
    if _restore_service is None:
        _restore_service = RestoreService()
    return _restore_service
