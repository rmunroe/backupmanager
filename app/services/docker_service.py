import asyncio
import docker
from docker.errors import NotFound, APIError
from dataclasses import dataclass


@dataclass
class ContainerStatus:
    name: str
    status: str  # running, exited, paused, restarting, etc.
    exists: bool = True


class DockerService:
    def __init__(self):
        self.client = docker.from_env()

    def get_container_status(self, name: str) -> ContainerStatus:
        """Get the status of a container by name."""
        try:
            container = self.client.containers.get(name)
            return ContainerStatus(
                name=name,
                status=container.status,
                exists=True,
            )
        except NotFound:
            return ContainerStatus(
                name=name,
                status="not_found",
                exists=False,
            )
        except APIError as e:
            return ContainerStatus(
                name=name,
                status=f"error: {str(e)}",
                exists=False,
            )

    def stop_container(self, name: str, timeout: int = 60) -> tuple[bool, str]:
        """Stop a container. Returns (success, message)."""
        try:
            container = self.client.containers.get(name)
            container.stop(timeout=timeout)
            return True, "Container stopped"
        except NotFound:
            return False, "Container not found"
        except APIError as e:
            return False, f"API error: {str(e)}"

    def start_container(self, name: str) -> tuple[bool, str]:
        """Start a container. Returns (success, message)."""
        try:
            container = self.client.containers.get(name)
            container.start()
            return True, "Container started"
        except NotFound:
            return False, "Container not found"
        except APIError as e:
            return False, f"API error: {str(e)}"

    def restart_container(self, name: str, timeout: int = 30) -> tuple[bool, str]:
        """Restart a container. Returns (success, message)."""
        try:
            container = self.client.containers.get(name)
            container.restart(timeout=timeout)
            return True, "Container restarted"
        except NotFound:
            return False, "Container not found"
        except APIError as e:
            return False, f"API error: {str(e)}"

    def is_running(self, name: str) -> bool:
        """Check if a container is running."""
        status = self.get_container_status(name)
        return status.status == "running"

    # Async wrappers for non-blocking calls
    async def get_container_status_async(self, name: str) -> ContainerStatus:
        """Async wrapper for get_container_status."""
        return await asyncio.to_thread(self.get_container_status, name)

    async def stop_container_async(self, name: str, timeout: int = 60) -> tuple[bool, str]:
        """Async wrapper for stop_container."""
        return await asyncio.to_thread(self.stop_container, name, timeout)

    async def start_container_async(self, name: str) -> tuple[bool, str]:
        """Async wrapper for start_container."""
        return await asyncio.to_thread(self.start_container, name)

    async def restart_container_async(self, name: str, timeout: int = 30) -> tuple[bool, str]:
        """Async wrapper for restart_container."""
        return await asyncio.to_thread(self.restart_container, name, timeout)

    async def is_running_async(self, name: str) -> bool:
        """Async wrapper for is_running."""
        return await asyncio.to_thread(self.is_running, name)

    def wait_for_log_message(
        self, name: str, pattern: str, timeout: int = 300, since_seconds: int = 0
    ) -> tuple[bool, str]:
        """
        Wait for a specific pattern to appear in container logs.
        Returns (found, message).
        """
        import re
        import time

        try:
            container = self.client.containers.get(name)
            start_time = time.time()
            since_timestamp = start_time - since_seconds if since_seconds else start_time

            while time.time() - start_time < timeout:
                # Get logs since the container started (or since specified time)
                logs = container.logs(since=int(since_timestamp), tail=100).decode("utf-8")

                if re.search(pattern, logs):
                    return True, "Pattern found in logs"

                time.sleep(2)

            return False, f"Timeout waiting for pattern after {timeout}s"
        except NotFound:
            return False, "Container not found"
        except APIError as e:
            return False, f"API error: {str(e)}"


_docker_service: DockerService | None = None


def get_docker_service() -> DockerService:
    global _docker_service
    if _docker_service is None:
        _docker_service = DockerService()
    return _docker_service
