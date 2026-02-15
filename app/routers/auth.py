from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth import get_auth_manager, check_auth

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page."""
    if check_auth(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    """Handle login form submission."""
    auth = get_auth_manager()

    if auth.verify_password(password):
        response = RedirectResponse(url="/", status_code=302)
        token = auth.create_session_token()
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            max_age=auth.max_age,
            samesite="lax",
        )
        return response

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password"},
        status_code=401,
    )


@router.post("/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="session")
    return response
