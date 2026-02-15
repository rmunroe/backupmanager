from pathlib import Path
from typing import List
from dataclasses import dataclass
from app.config import get_settings
from app.services.docker_service import DockerService, get_docker_service


@dataclass
class ServerInfo:
    name: str
    status: str
    data_path: str
    backups_path: str
    has_backups: bool


class ServerService:
    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self.base_path = Path(base_path or settings.servers_base_path)
        self.docker = get_docker_service()

    def discover_servers(self) -> List[str]:
        """Find all directories with data/ and backups/ subdirectories."""
        servers = []
        if not self.base_path.exists():
            return servers

        for entry in self.base_path.iterdir():
            if entry.is_dir():
                data_dir = entry / "data"
                backups_dir = entry / "backups"
                if data_dir.is_dir() and backups_dir.is_dir():
                    servers.append(entry.name)
        return sorted(servers)

    def get_server_info(self, name: str) -> ServerInfo | None:
        """Get detailed info about a specific server."""
        if not self.is_valid_server(name):
            return None

        server_path = self.base_path / name
        backups_path = server_path / "backups"

        # Check if there are any backup files
        has_backups = any(
            f.is_file() and not f.is_symlink() and f.suffix in (".tgz", ".gz")
            for f in backups_path.iterdir()
        ) if backups_path.exists() else False

        # Get container status
        container_status = self.docker.get_container_status(name)

        return ServerInfo(
            name=name,
            status=container_status.status,
            data_path=str(server_path / "data"),
            backups_path=str(backups_path),
            has_backups=has_backups,
        )

    def get_all_servers(self) -> List[ServerInfo]:
        """Get info for all discovered servers."""
        servers = []
        for name in self.discover_servers():
            info = self.get_server_info(name)
            if info:
                servers.append(info)
        return servers

    def is_valid_server(self, name: str) -> bool:
        """Validate server name to prevent path traversal."""
        if not name:
            return False
        if "/" in name or "\\" in name or ".." in name:
            return False
        return name in self.discover_servers()


def get_server_service() -> ServerService:
    return ServerService()
