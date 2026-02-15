import re
from pathlib import Path
from datetime import datetime
from typing import List
from dataclasses import dataclass
from app.config import get_settings


@dataclass
class BackupInfo:
    filename: str
    datetime: datetime
    size_bytes: int
    size_human: str


class BackupService:
    # Pattern: world-YYYYMMDD-HHMMSS.tgz or .tar.gz
    BACKUP_PATTERN = re.compile(r"^world-(\d{8})-(\d{6})\.(tgz|tar\.gz)$")

    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self.base_path = Path(base_path or settings.servers_base_path)

    def list_backups(self, server_name: str) -> List[BackupInfo]:
        """List all backups for a server, sorted newest first."""
        backup_dir = self.base_path / server_name / "backups"
        backups = []

        if not backup_dir.exists():
            return backups

        for entry in backup_dir.iterdir():
            # Skip symlinks (latest.tgz, latest.tar.gz)
            if entry.is_symlink():
                continue

            if not entry.is_file():
                continue

            match = self.BACKUP_PATTERN.match(entry.name)
            if match:
                date_str, time_str, _ = match.groups()
                try:
                    dt = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
                    size = entry.stat().st_size

                    backups.append(
                        BackupInfo(
                            filename=entry.name,
                            datetime=dt,
                            size_bytes=size,
                            size_human=self._format_size(size),
                        )
                    )
                except ValueError:
                    # Skip files with invalid date formats
                    continue

        return sorted(backups, key=lambda b: b.datetime, reverse=True)

    def get_backup(self, server_name: str, filename: str) -> BackupInfo | None:
        """Get info about a specific backup file."""
        backups = self.list_backups(server_name)
        for backup in backups:
            if backup.filename == filename:
                return backup
        return None

    def backup_exists(self, server_name: str, filename: str) -> bool:
        """Check if a backup file exists (and is not a symlink)."""
        backup_path = self.base_path / server_name / "backups" / filename
        return backup_path.is_file() and not backup_path.is_symlink()

    def get_backup_path(self, server_name: str, filename: str) -> Path | None:
        """Get the full path to a backup file."""
        if not self.backup_exists(server_name, filename):
            return None
        return self.base_path / server_name / "backups" / filename

    @staticmethod
    def _format_size(size: int) -> str:
        """Format bytes to human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def get_backup_service() -> BackupService:
    return BackupService()
