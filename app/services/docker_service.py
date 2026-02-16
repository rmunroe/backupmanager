import docker
from docker.errors import NotFound, APIError
from typing import Optional
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


def get_docker_service() -> DockerService:
    return DockerService()
