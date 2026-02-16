import docker
import logging
import re
import shutil
import tarfile
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Dict
from dataclasses import dataclass, field
from app.config import get_settings

logger = logging.getLogger(__name__)

# Thread pool for background restore operations
_restore_executor = None

def get_restore_executor():
    global _restore_executor
    if _restore_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _restore_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="restore")
    return _restore_executor


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
        self.jobs: Dict[str, RestoreJob] = {}
        self._active_restores: Dict[str, str] = {}  # server_name -> job_id
        self._lock = threading.Lock()

    def create_job(self, server_name: str, backup_file: str) -> RestoreJob | None:
        """Create a new restore job. Returns None if restore already in progress."""
        with self._lock:
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
        with self._lock:
            return self.jobs.get(job_id)

    def start_restore(self, job_id: str) -> None:
        """Start restore operation in a background thread (fire and forget)."""
        executor = get_restore_executor()
        executor.submit(self._execute_restore_sync, job_id)

    def _execute_restore_sync(self, job_id: str) -> bool:
        """Execute restore operation synchronously (runs in thread)."""
        logger.info(f"Starting restore for job {job_id}")
        job = self.jobs.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found!")
            return False

        server_path = self.base_path / job.server_name
        data_dir = server_path / "data"
        backup_path = server_path / "backups" / job.backup_file

        logger.info(f"Job {job_id}: server={job.server_name}, backup={backup_path}")

        # Create a fresh Docker client for this thread
        docker_client = docker.from_env()

        try:
            # Step 1: Check container status
            self._update_job(
                job, RestoreStep.STOPPING, 5, "Checking container status..."
            )

            backup_container_name = f"{job.server_name}-backup"

            is_running = self._is_container_running(docker_client, job.server_name)
            backup_is_running = self._is_container_running(docker_client, backup_container_name)

            if is_running:
                job.container_was_running = True
                self._update_job(
                    job, RestoreStep.STOPPING, 10, "Stopping server container..."
                )

                try:
                    container = docker_client.containers.get(job.server_name)
                    container.stop(timeout=60)
                except Exception as e:
                    raise Exception(f"Failed to stop container: {e}")

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

            shutil.rmtree(data_dir, ignore_errors=True)
            data_dir.mkdir(parents=True, exist_ok=True)

            self._update_job(
                job, RestoreStep.CLEARING, 40, "Data directory cleared"
            )

            # Step 3: Extract backup
            self._update_job(
                job, RestoreStep.EXTRACTING, 45, "Extracting backup..."
            )

            self._extract_backup(backup_path, data_dir)

            self._update_job(
                job, RestoreStep.EXTRACTING, 85, "Backup extracted"
            )

            # Step 4: Restart containers if they were running
            if job.container_was_running:
                self._update_job(
                    job, RestoreStep.STARTING, 87, "Starting server container..."
                )

                try:
                    container = docker_client.containers.get(job.server_name)
                    container.start()
                except Exception as e:
                    raise Exception(f"Failed to start container: {e}")

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

                try:
                    container = docker_client.containers.get(backup_container_name)
                    container.restart(timeout=30)
                    self._update_job(
                        job, RestoreStep.STARTING, 94, "Backup container restarted"
                    )
                except Exception as e:
                    # Non-fatal
                    self._update_job(
                        job, RestoreStep.STARTING, 94, f"Warning: Could not restart backup container: {e}"
                    )

            # Step 5: Wait for Minecraft to be ready (if server was running)
            if job.container_was_running:
                self._update_job(
                    job, RestoreStep.WAITING_READY, 95, "Waiting for Minecraft server to start..."
                )

                # Wait for "Done (XXs)! For help, type" message in logs
                ready_pattern = r'Done \([0-9.]+s\)! For help'
                timeout = 300
                start_time = time.time()
                found = False

                try:
                    container = docker_client.containers.get(job.server_name)
                    since_timestamp = int(start_time) - 10

                    while time.time() - start_time < timeout:
                        logs = container.logs(since=since_timestamp, tail=100).decode("utf-8")
                        if re.search(ready_pattern, logs):
                            found = True
                            break
                        time.sleep(2)
                except Exception as e:
                    logger.warning(f"Error checking logs: {e}")

                if found:
                    self._update_job(
                        job, RestoreStep.WAITING_READY, 99, "Minecraft server is ready! Players can join."
                    )
                else:
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
            with self._lock:
                if self._active_restores.get(job.server_name) == job_id:
                    del self._active_restores[job.server_name]

    def _is_container_running(self, client, name: str) -> bool:
        """Check if container is running."""
        try:
            container = client.containers.get(name)
            return container.status == "running"
        except Exception:
            return False

    def _extract_backup(self, backup_path: Path, data_dir: Path):
        """Extract tarball to data directory."""
        with tarfile.open(backup_path, "r:gz") as tar:
            tar.extractall(path=data_dir, filter="data")

    def _update_job(
        self, job: RestoreJob, step: RestoreStep, progress: int, message: str
    ):
        """Update job status."""
        with self._lock:
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
