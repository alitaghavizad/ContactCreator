import json

import anthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.cv_parser import CVExtractionError, CVParseError, extract_pdf_text, parse_cv
from app.db import get_db
from app.models import Profile, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).first()
    if user is None:
        user = User(email="local-user@contactcreator.local")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.get("/intake")
def show_intake_form(request: Request):
    return templates.TemplateResponse("intake.html", {"request": request})


@router.post("/intake")
async def submit_intake(
    cv_file: UploadFile = File(...),
    target_roles: str = Form(...),
    target_locations: str = Form(...),
    domains: str = Form(...),
    seniority: str = Form(...),
    tone: str = Form("professional"),
    db: Session = Depends(get_db),
):
    filename = cv_file.filename.lower()
    if not (filename.endswith(".txt") or filename.endswith(".pdf")):
        raise HTTPException(
            status_code=400,
            detail="Please upload a plain text (.txt) or PDF (.pdf) CV file.",
        )

    cv_bytes = await cv_file.read()
    if filename.endswith(".pdf"):
        try:
            cv_text = extract_pdf_text(cv_bytes)
        except CVExtractionError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        cv_text = cv_bytes.decode("utf-8", errors="ignore")

    questionnaire_answers = (
        f"Target roles: {target_roles}\n"
        f"Target locations: {target_locations}\n"
        f"Domains: {domains}\n"
        f"Seniority: {seniority}\n"
        f"Tone: {tone}"
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        # parse_cv makes a blocking Anthropic SDK call; run it off the event
        # loop so it does not stall every other request while it is in flight.
        structured = await run_in_threadpool(
            parse_cv,
            cv_text=cv_text,
            questionnaire_answers=questionnaire_answers,
            client=client,
            model=settings.claude_model,
        )
    except CVParseError:
        raise HTTPException(
            status_code=502, detail="Could not process your CV. Please try again."
        )

    user = get_or_create_default_user(db)
    profile = db.query(Profile).filter_by(user_id=user.id).first()
    if profile is None:
        profile = Profile(user_id=user.id, cv_text=cv_text)
        db.add(profile)

    profile.cv_text = cv_text
    profile.skills = json.dumps(structured.skills)
    profile.years_experience = structured.years_experience
    profile.domains = json.dumps(structured.domains)
    profile.target_roles = json.dumps(structured.target_roles)
    profile.target_locations = json.dumps(structured.target_locations)
    profile.seniority = structured.seniority
    profile.tone = structured.tone
    db.commit()

    return RedirectResponse(url="/contacts", status_code=303)
