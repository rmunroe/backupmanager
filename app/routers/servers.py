from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.auth import require_auth
from app.config import get_settings
from app.services.server_service import get_server_service
from app.services.backup_service import get_backup_service
from app.services.docker_service import get_docker_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Add version to template globals
templates.env.globals["app_version"] = get_settings().app_version


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _=Depends(require_auth)):
    """Main dashboard showing all servers."""
    server_service = get_server_service()
    servers = await server_service.get_all_servers()

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "servers": servers},
    )


@router.get("/servers/{server_name}", response_class=HTMLResponse)
async def server_detail(request: Request, server_name: str, _=Depends(require_auth)):
    """Server detail page with backup list."""
    server_service = get_server_service()
    backup_service = get_backup_service()

    server = await server_service.get_server_info(server_name)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    backups = backup_service.list_backups(server_name)

    return templates.TemplateResponse(
        "server.html",
        {"request": request, "server": server, "backups": backups},
    )


@router.post("/api/servers/{server_name}/start")
async def start_server(server_name: str, _=Depends(require_auth)):
    """Start a server container."""
    server_service = get_server_service()
    docker_service = get_docker_service()

    if not server_service.is_valid_server(server_name):
        raise HTTPException(status_code=404, detail="Server not found")

    success, message = await docker_service.start_container_async(server_name)

    if success:
        return {"status": "ok", "message": message}
    else:
        raise HTTPException(status_code=500, detail=message)


@router.post("/api/servers/{server_name}/stop")
async def stop_server(server_name: str, _=Depends(require_auth)):
    """Stop a server container."""
    server_service = get_server_service()
    docker_service = get_docker_service()

    if not server_service.is_valid_server(server_name):
        raise HTTPException(status_code=404, detail="Server not found")

    success, message = await docker_service.stop_container_async(server_name)

    if success:
        return {"status": "ok", "message": message}
    else:
        raise HTTPException(status_code=500, detail=message)


@router.get("/api/servers/{server_name}/status")
async def server_status(server_name: str, _=Depends(require_auth)):
    """Get current server status."""
    server_service = get_server_service()
    docker_service = get_docker_service()

    if not server_service.is_valid_server(server_name):
        raise HTTPException(status_code=404, detail="Server not found")

    status = await docker_service.get_container_status_async(server_name)

    return {"name": server_name, "status": status.status, "exists": status.exists}
