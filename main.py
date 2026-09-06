from contextlib import contextmanager
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Khelo API", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@contextmanager
def get_database_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    with psycopg.connect(database_url) as connection:
        yield connection


@app.get("/", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "login.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/sports")
def list_sports() -> list[dict[str, object]]:
    """Return the sports lookup values used by the venue-registration dropdown."""
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name FROM sports ORDER BY name")
                return [
                    {"id": sport_id, "name": sport_name}
                    for sport_id, sport_name in cursor.fetchall()
                ]
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(
            status_code=503, detail="Sports are temporarily unavailable."
        ) from error