# Minecraft Backup Manager

A web application for managing Minecraft server backup restorations across multiple Docker-based servers.

## Project Goals

Replace the manual process of running `restore.sh` scripts with a user-friendly web interface that allows:

1. **Visibility** - See all Minecraft servers and their current status at a glance
2. **Control** - Start/stop server containers directly from the UI
3. **Easy Restores** - Browse backups by date/time/size and restore with one click
4. **Safety** - Confirmation dialogs and real-time progress feedback during restores

## Server Environment

- **Host path**: `/opt/docker/<servername>/`
- **Structure**: Each server has `data/` (live server) and `backups/` directories
- **Server image**: `itzg/minecraft-server`
- **Backup image**: `itzg/mc-backup`
- **Backup format**: `world-YYYYMMDD-HHMMSS.tgz` or `.tar.gz`

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.12 + FastAPI |
| Frontend | Jinja2 templates + vanilla JS |
| Styling | Pico CSS (classless dark theme) |
| Auth | Simple password with signed session cookies |
| Deployment | Docker container |

## Features

### Dashboard (`/`)
- Grid of all discovered Minecraft servers
- Status badge for each server (running/stopped/etc.)
- Quick Start/Stop buttons
- Link to backup list for each server

### Server Detail (`/servers/{name}`)
- Current server status with Start/Stop controls
- Table of all backups sorted by date (newest first)
- Columns: Date, Time, File Size, Restore button
- Restore confirmation modal with warning

### Restore Process
Mirrors the existing `restore.sh` workflow:
1. Check if container is running (save state)
2. Stop server container if running (60s timeout)
3. Delete `/opt/docker/{server}/data/` contents
4. Extract backup tarball to data directory
5. Restart server container only if it was running before
6. Restart backup container (`{server}-backup`) if it was running
7. Wait for Minecraft server to be ready (monitors logs for "Done" message)
8. Report progress via WebSocket in real-time

### Authentication
- Single shared password (configured via environment variable)
- Session cookie with 24-hour expiry
- All routes protected except `/login`

## Project Structure

```
/home/robert/backupmanager/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Settings from environment variables
│   ├── auth.py              # Password auth + session handling
│   ├── services/
│   │   ├── docker_service.py   # Container start/stop/status via Docker API
│   │   ├── server_service.py   # Discover servers from filesystem
│   │   ├── backup_service.py   # List and parse backup files
│   │   └── restore_service.py  # Async restore orchestration with progress
│   ├── routers/
│   │   ├── auth.py          # Login/logout routes
│   │   ├── servers.py       # Server list, detail, start/stop API
│   │   └── restore.py       # Restore API + WebSocket progress
│   ├── static/
│   │   ├── style.css        # Custom styles
│   │   └── app.js           # Utility functions
│   └── templates/
│       ├── base.html        # Base template with nav
│       ├── login.html       # Login page
│       ├── index.html       # Server dashboard
│       └── server.html      # Server detail + backup list
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                     # Local environment config
├── .env.example             # Example environment config
└── README.md
```

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/login` | Login page |
| POST | `/login` | Authenticate with password |
| POST | `/logout` | Clear session |

### Servers
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard with all servers |
| GET | `/servers/{name}` | Server detail page with backups |
| POST | `/api/servers/{name}/start` | Start server container |
| POST | `/api/servers/{name}/stop` | Stop server container |
| GET | `/api/servers/{name}/status` | Get server status (JSON) |

### Restore
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/servers/{name}/restore` | Initiate restore (body: `{"backup": "filename"}`) |
| GET | `/api/restore/{job_id}/status` | Get restore job status |
| WS | `/ws/restore/{job_id}` | Real-time progress updates |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check endpoint |

## Deployment

### Using Pre-built Image (Recommended)

The application is automatically built and pushed to GitHub Container Registry on every push to `master`.

```yaml
# docker-compose.yml
services:
  backupmanager:
    image: ghcr.io/rmunroe/backupmanager:latest
    container_name: backupmanager
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /opt/docker:/opt/docker
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - APP_PASSWORD=${APP_PASSWORD}
      - SECRET_KEY=${SECRET_KEY}
```

### Prerequisites
- Docker and Docker Compose installed
- Access to `/opt/docker` directory
- Access to Docker socket (`/var/run/docker.sock`)

### Configuration

Edit `.env` file:

```bash
# Application password for web UI access
APP_PASSWORD=your-secure-password

# Secret key for session signing
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-secret-key-here
```

### Build and Run

```bash
cd /home/robert/backupmanager
docker compose up -d --build
```

### Access

Open http://your-server:8080 in a browser.

## CI/CD with GitHub Actions

The project includes a GitHub Actions workflow (`.github/workflows/build.yml`) that:

1. Builds the Docker image on every push to `master`
2. Pushes to GitHub Container Registry (`ghcr.io`)
3. Tags with `latest` and the commit SHA
4. Triggers a Portainer webhook for automatic deployment

### Setting up Portainer Auto-Deploy

1. In Portainer, create a stack using "Repository" with your GitHub repo
2. Enable "GitOps updates" and note the webhook URL
3. In GitHub repo settings, add a secret named `PORTAINER_WEBHOOK_URL` with the webhook URL
4. The workflow will trigger Portainer to pull the new image after each successful build

### Version Display

The application displays the build version (Git commit SHA) in the footer. This is passed as a build argument during the Docker build:

```yaml
build-args: |
  BUILD_VERSION=${{ github.sha }}
```

## Security Considerations

1. **Docker Socket Access** - The container has access to the Docker socket, which provides significant host control. Run only on trusted networks.

2. **File System Access** - The container has read/write access to `/opt/docker` for restore operations.

3. **Path Traversal Protection** - Server names are validated against discovered servers to prevent directory traversal attacks.

4. **Concurrent Restore Prevention** - Only one restore can run per server at a time.

5. **Network Recommendations**:
   - Run behind a reverse proxy with HTTPS
   - Restrict access to trusted networks/VPN
   - Consider additional authentication layer (e.g., Authelia, Authentik)

## Current Status

**Status: Complete - In Production**

### Completed Features
- [x] Project structure and configuration
- [x] Docker service (container start/stop/status)
- [x] Server discovery service
- [x] Backup listing and parsing service
- [x] Async restore service with progress tracking
- [x] Authentication system (password + sessions)
- [x] Dashboard UI with server grid
- [x] Server detail page with backup table
- [x] Restore confirmation modal
- [x] WebSocket progress updates during restore
- [x] Polling fallback for progress
- [x] Dockerfile and docker-compose.yml
- [x] CSS styling with Pico CSS
- [x] GitHub Actions CI/CD pipeline
- [x] Auto-deploy via Portainer webhook
- [x] Version display in footer
- [x] Backup container restart after restore
- [x] Minecraft server ready detection

### Future Enhancements (Not Implemented)
- [ ] Pre-restore backup creation (safety snapshot)
- [ ] Backup deletion/cleanup
- [ ] Log viewing
- [ ] Multiple user accounts
- [ ] Audit logging
- [ ] Email/webhook notifications on restore completion
