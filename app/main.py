from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import get_current_user, hash_password, verify_password
from app.database import Base, SessionLocal, engine, get_db
from app.models import Device, Lab, Submission, User
from app.services.device_ops import apply_config_to_device, fetch_running_config
from app.services.grader import grade_config
from app.settings import APP_SESSION_SECRET, GUACAMOLE_BASE_URL

app = FastAPI(title="Guacamole Lab Portal")
app.add_middleware(SessionMiddleware, secret_key=APP_SESSION_SECRET)

templates = Jinja2Templates(directory="app/templates")
static_dir = Path("app/static")
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def ensure_seed_data(db: Session):
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        db.add(User(username="admin", password_hash=hash_password("admin123"), role="admin"))
    student = db.query(User).filter(User.username == "student1").first()
    if not student:
        db.add(User(username="student1", password_hash=hash_password("student123"), role="student"))
    if db.query(Device).count() == 0:
        for i in range(1, 37):
            db.add(
                Device(
                    name=f"R{i}",
                    host="127.0.0.1",
                    port=2000 + i,
                    guacamole_connection_id=str(i),
                    assigned_user_id=None,
                )
            )
    if db.query(Lab).count() == 0:
        db.add(
            Lab(
                title="Lab 1: Base Config",
                description="Configure hostname, VLAN interface and OSPF basics.",
                check_rules="hostname\\s+R\\d+\ninterface\\s+vlan\\s+1\nrouter\\s+ospf\\s+1",
            )
        )
    db.commit()


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_seed_data(db)
    finally:
        db.close()


def require_role(user: User, role: str):
    if user.role != role:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"request": request, "error": "Invalid credentials"},
            status_code=401,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user.role == "admin":
        devices = db.query(Device).order_by(Device.id).all()
        labs = db.query(Lab).order_by(Lab.id.desc()).all()
        return templates.TemplateResponse(
            request=request,
            name="admin_dashboard.html",
            context={
                "request": request,
                "user": user,
                "devices": devices,
                "labs": labs,
                "message": None,
                "guacamole_base_url": GUACAMOLE_BASE_URL,
            },
        )

    labs = db.query(Lab).filter(Lab.is_active.is_(True)).order_by(Lab.id.desc()).all()
    submissions = (
        db.query(Submission).filter(Submission.user_id == user.id).order_by(Submission.id.desc()).limit(10).all()
    )
    assigned_device = db.query(Device).filter(Device.assigned_user_id == user.id).first()
    return templates.TemplateResponse(
        request=request,
        name="student_dashboard.html",
        context={
            "request": request,
            "user": user,
            "labs": labs,
            "submissions": submissions,
            "assigned_device": assigned_device,
            "message": None,
            "guacamole_base_url": GUACAMOLE_BASE_URL,
        },
    )


@app.post("/admin/labs/create")
def create_lab(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    check_rules: str = Form(...),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    require_role(user, "admin")
    db.add(Lab(title=title, description=description, check_rules=check_rules, is_active=is_active))
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/admin/labs/{lab_id}/toggle")
def toggle_lab(lab_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    require_role(user, "admin")
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")
    lab.is_active = not lab.is_active
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/admin/devices/assign")
def assign_device(
    request: Request,
    device_id: int = Form(...),
    student_username: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    require_role(user, "admin")
    device = db.query(Device).filter(Device.id == device_id).first()
    student = db.query(User).filter(User.username == student_username, User.role == "student").first()
    if not device or not student:
        raise HTTPException(status_code=404, detail="Device or student not found")
    existing_device = db.query(Device).filter(Device.assigned_user_id == student.id).first()
    if existing_device and existing_device.id != device.id:
        existing_device.assigned_user_id = None
    device.assigned_user_id = student.id
    db.commit()
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/admin/config/push", response_class=HTMLResponse)
async def push_config(
    request: Request,
    device_ids: list[int] = Form(...),
    config_file: UploadFile | None = None,
    config_text: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    require_role(user, "admin")

    content = config_text.strip()
    if config_file and not content:
        raw = await config_file.read()
        content = raw.decode("utf-8", errors="replace")
    if not content:
        raise HTTPException(status_code=400, detail="Provide config text or upload file")

    devices = db.query(Device).filter(Device.id.in_(device_ids)).all()
    logs = [apply_config_to_device(device, content) for device in devices]

    devices_all = db.query(Device).order_by(Device.id).all()
    labs = db.query(Lab).order_by(Lab.id.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "request": request,
            "user": user,
            "devices": devices_all,
            "labs": labs,
            "message": "\n".join(logs) if logs else "No devices selected",
            "guacamole_base_url": GUACAMOLE_BASE_URL,
        },
    )


@app.post("/student/submit", response_class=HTMLResponse)
def submit_lab(
    request: Request,
    lab_id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    require_role(user, "student")
    lab = db.query(Lab).filter(Lab.id == lab_id, Lab.is_active.is_(True)).first()
    if not lab:
        raise HTTPException(status_code=404, detail="Lab not found")

    device = db.query(Device).filter(Device.assigned_user_id == user.id).first()
    if not device:
        raise HTTPException(status_code=400, detail="No assigned device for this student")

    config = fetch_running_config(device)
    score, result = grade_config(config, lab.check_rules)
    submission = Submission(
        user_id=user.id,
        device_id=device.id,
        lab_id=lab.id,
        fetched_config=config,
        score=score,
        result_text=result,
    )
    db.add(submission)
    db.commit()

    labs = db.query(Lab).filter(Lab.is_active.is_(True)).order_by(Lab.id.desc()).all()
    submissions = (
        db.query(Submission).filter(Submission.user_id == user.id).order_by(Submission.id.desc()).limit(10).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="student_dashboard.html",
        context={
            "request": request,
            "user": user,
            "labs": labs,
            "submissions": submissions,
            "assigned_device": device,
            "message": f"Submission saved. Score: {score}%",
            "guacamole_base_url": GUACAMOLE_BASE_URL,
        },
    )
