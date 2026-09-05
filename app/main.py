from fastapi import FastAPI

app = FastAPI(title="ContactCreator")


@app.get("/health")
def health():
    return {"status": "ok"}
