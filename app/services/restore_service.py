import asyncio
import uuid
import shutil
import tarfile
import logging
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Dict
from dataclasses import dataclass, field
from app.config import get_settings
from app.services.docker_service import get_docker_service

logger = logging.getLogger(__name__)


class RestoreStep(str, Enum):
    PENDING = "pending"
    STOPPING = "stopping"
    CLEARING = "clearing"
    EXTRACTING = "extracting"
    STARTING = "starting"
    WAITING_READY = "waiting_ready"
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
    backup_container_was_running: bool = False


class RestoreService:
    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self.base_path = Path(base_path or settings.servers_base_path)
        self.docker = get_docker_service()
        self.jobs: Dict[str, RestoreJob] = {}
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
        print(f"[RESTORE] Starting execute_restore for job {job_id}", flush=True)
        job = self.jobs.get(job_id)
        if not job:
            print(f"[RESTORE] Job {job_id} not found!", flush=True)
            return False

        server_path = self.base_path / job.server_name
        data_dir = server_path / "data"
        backup_path = server_path / "backups" / job.backup_file

        print(f"[RESTORE] Job {job_id}: server={job.server_name}, backup={backup_path}", flush=True)

        try:
            # Step 1: Check container status
            self._update_job(
                job, RestoreStep.STOPPING, 5, "Checking container status..."
            )

            backup_container_name = f"{job.server_name}-backup"

            is_running = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.docker.is_running(job.server_name)
            )
            backup_is_running = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.docker.is_running(backup_container_name)
            )

            if is_running:
                job.container_was_running = True
                self._update_job(
                    job, RestoreStep.STOPPING, 10, "Stopping server container..."
                )

                success, msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.docker.stop_container(job.server_name, timeout=60)
                )

                if not success:
                    raise Exception(f"Failed to stop container: {msg}")

                self._update_job(
                    job, RestoreStep.STOPPING, 20, "Server container stopped"
                )
            else:
                job.container_was_running = False
                self._update_job(
                    job, RestoreStep.STOPPING, 20, "Server container not running"
                )

            # Also track backup container state
            job.backup_container_was_running = backup_is_running

            # Step 2: Clear data directory
            self._update_job(
                job, RestoreStep.CLEARING, 30, "Removing old data..."
            )

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: shutil.rmtree(data_dir, ignore_errors=True)
            )

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: data_dir.mkdir(parents=True, exist_ok=True)
            )

            self._update_job(
                job, RestoreStep.CLEARING, 40, "Data directory cleared"
            )

            # Step 3: Extract backup
            self._update_job(
                job, RestoreStep.EXTRACTING, 45, "Extracting backup..."
            )

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._extract_backup(backup_path, data_dir)
            )

            self._update_job(
                job, RestoreStep.EXTRACTING, 85, "Backup extracted"
            )

            # Step 4: Restart containers if they were running
            if job.container_was_running:
                self._update_job(
                    job, RestoreStep.STARTING, 87, "Starting server container..."
                )

                success, msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.docker.start_container(job.server_name)
                )

                if not success:
                    raise Exception(f"Failed to start container: {msg}")

                self._update_job(
                    job, RestoreStep.STARTING, 92, "Server container started"
                )
            else:
                self._update_job(
                    job, RestoreStep.STARTING, 92, "Server container left stopped (was not running before)"
                )

            # Restart backup container if it was running
            if job.backup_container_was_running:
                self._update_job(
                    job, RestoreStep.STARTING, 93, "Restarting backup container..."
                )

                success, msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.docker.restart_container(backup_container_name)
                )

                if not success:
                    # Non-fatal - just log it in the message
                    self._update_job(
                        job, RestoreStep.STARTING, 94, f"Warning: Could not restart backup container: {msg}"
                    )
                else:
                    self._update_job(
                        job, RestoreStep.STARTING, 94, "Backup container restarted"
                    )

            # Step 5: Wait for Minecraft to be ready (if server was running)
            if job.container_was_running:
                self._update_job(
                    job, RestoreStep.WAITING_READY, 95, "Waiting for Minecraft server to start..."
                )

                # Wait for "Done (XXs)! For help, type" message in logs
                ready_pattern = r'Done \([0-9.]+s\)! For help'
                found, msg = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.docker.wait_for_log_message(
                        job.server_name, ready_pattern, timeout=300, since_seconds=10
                    )
                )

                if found:
                    self._update_job(
                        job, RestoreStep.WAITING_READY, 99, "Minecraft server is ready! Players can join."
                    )
                else:
                    # Non-fatal - server might still be starting
                    self._update_job(
                        job, RestoreStep.WAITING_READY, 99, "Server started (ready check timed out - may still be loading)"
                    )

            # Complete
            job.completed_at = datetime.now()
            self._update_job(
                job, RestoreStep.COMPLETED, 100, "Restore completed successfully!"
            )
            return True

        except Exception as e:
            logger.exception(f"Restore {job.id} failed: {e}")
            job.error = str(e)
            job.completed_at = datetime.now()
            self._update_job(
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

    def _update_job(
        self, job: RestoreJob, step: RestoreStep, progress: int, message: str
    ):
        """Update job status."""
        job.step = step
        job.progress = progress
        job.message = message
        logger.info(f"Restore {job.id}: [{progress}%] {step.value} - {message}")


# Singleton instance
_restore_service: RestoreService | None = None


def get_restore_service() -> RestoreService:
    global _restore_service
    if _restore_service is None:
        _restore_service = RestoreService()
    return _restore_service
