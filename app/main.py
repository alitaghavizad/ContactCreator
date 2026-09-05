from fastapi import FastAPI

from app.db import engine
from app.models import Base

app = FastAPI(title="ContactCreator")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}
