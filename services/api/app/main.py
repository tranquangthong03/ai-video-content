from fastapi import FastAPI

app = FastAPI(title="Short Video AI API")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by docker healthcheck."""
    return {"status": "ok"}
