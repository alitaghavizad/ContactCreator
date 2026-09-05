from fastapi import FastAPI

from app.db import engine
from app.models import Base
from app.routes.discovery import router as discovery_router
from app.routes.intake import router as intake_router

app = FastAPI(title="ContactCreator")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(intake_router)
app.include_router(discovery_router)
