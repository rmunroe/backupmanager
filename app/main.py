from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.routers import auth, servers, restore
from app.auth import check_auth

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

    # Allow login page, static files, health check, and API endpoints (which have their own auth)
    if path.startswith("/login") or path.startswith("/static") or path == "/health":
        return await call_next(request)

    # Check auth for HTML pages
    if not path.startswith("/api") and not path.startswith("/ws"):
        if not check_auth(request):
            return RedirectResponse(url="/login", status_code=302)

    return await call_next(request)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
