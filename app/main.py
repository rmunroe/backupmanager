import logging
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.routers import auth, servers, restore
from app.auth import check_auth
from app.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()
print(f"", flush=True)
print(f"========================================", flush=True)
print(f"  Minecraft Backup Manager", flush=True)
print(f"  Version: {settings.app_version[:7] if settings.app_version != 'dev' else 'dev'}", flush=True)
print(f"========================================", flush=True)
print(f"", flush=True)

app = FastAPI(title="Minecraft Backup Manager")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(servers.router)
app.include_router(restore.router)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Redirect to login if not authenticated (except for login page and static files)."""
    path = request.url.path
    start_time = time.time()
    logger.info(f"Request started: {request.method} {path}")

    # Allow login page, static files, health check, and API endpoints (which have their own auth)
    if path.startswith("/login") or path.startswith("/static") or path == "/health":
        response = await call_next(request)
        # Disable caching
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        logger.info(f"Request finished: {request.method} {path} - {time.time() - start_time:.2f}s")
        return response

    # Check auth for HTML pages
    if not path.startswith("/api") and not path.startswith("/ws"):
        if not check_auth(request):
            return RedirectResponse(url="/login", status_code=302)

    response = await call_next(request)
    # Disable caching
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    logger.info(f"Request finished: {request.method} {path} - {time.time() - start_time:.2f}s")
    return response


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
