from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl, field_validator
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Khelo API", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str = "player"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"player", "court_manager"}:
            raise ValueError("role must be player or court_manager")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ProfileRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    profile_picture_url: HttpUrl | None = None


class VenueRequest(BaseModel):
    manager_id: UUID
    name: str = Field(min_length=2, max_length=160)
    sport_id: int
    address: str = Field(min_length=2, max_length=300)
    google_maps_url: HttpUrl
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    slot_duration_minutes: int = Field(ge=15, le=240)
    opens_at: str
    closes_at: str
    booking_price_cents: int = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    photo_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def user_response(user_id: UUID, email: str, role: str, full_name: str | None) -> dict:
    return {
        "user_id": str(user_id),
        "email": email,
        "role": role,
        "profile_required": not bool(full_name),
    }


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


@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest) -> dict:
    user_id = uuid4()
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (id, email, password_hash, role)
                    VALUES (%s, %s, %s, %s)
                    RETURNING email, role
                    """,
                    (user_id, payload.email, hash_password(payload.password), payload.role),
                )
                created_user = cursor.fetchone()
                if not created_user:
                    raise HTTPException(status_code=500, detail="Account could not be created.")
                email, role = created_user
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from error
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Account creation is temporarily unavailable.") from error

    return user_response(user_id, email, role, None)


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict:
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, email, password_hash, role, full_name FROM users WHERE email = %s",
                    (payload.email,),
                )
                user = cursor.fetchone()
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Login is temporarily unavailable.") from error

    if not user or not user[2] or not verify_password(payload.password, user[2]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return user_response(user[0], user[1], user[3], user[4])


@app.put("/api/users/{user_id}/profile")
def complete_profile(user_id: UUID, payload: ProfileRequest) -> dict:
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET full_name = %s, profile_picture_url = %s, profile_completed_at = %s
                    WHERE id = %s
                    RETURNING id, email, role, full_name, profile_picture_url
                    """,
                    (
                        payload.full_name.strip(),
                        str(payload.profile_picture_url) if payload.profile_picture_url else None,
                        datetime.now(timezone.utc),
                        user_id,
                    ),
                )
                user = cursor.fetchone()
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Profile update is temporarily unavailable.") from error

    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "user_id": str(user[0]),
        "email": user[1],
        "role": user[2],
        "full_name": user[3],
        "profile_picture_url": user[4],
        "profile_required": False,
    }


@app.get("/venues/new", include_in_schema=False)
def venue_signup_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "venue-signup.html")


@app.post("/api/venues", status_code=status.HTTP_201_CREATED)
def register_venue(payload: VenueRequest) -> dict:
    venue_id = uuid4()
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT role FROM users WHERE id = %s", (payload.manager_id,))
                manager = cursor.fetchone()
                if not manager or manager[0] != "court_manager":
                    raise HTTPException(status_code=403, detail="Only court managers can register venues.")

                cursor.execute(
                    """
                    INSERT INTO venues (
                        id, manager_id, sport_id, name, address, google_maps_url,
                        latitude, longitude, slot_duration_minutes, opens_at,
                        closes_at, booking_price_cents, currency
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, name, sport_id
                    """,
                    (
                        venue_id, payload.manager_id, payload.sport_id, payload.name.strip(),
                        payload.address.strip(), str(payload.google_maps_url), payload.latitude,
                        payload.longitude, payload.slot_duration_minutes, payload.opens_at,
                        payload.closes_at, payload.booking_price_cents, payload.currency.upper(),
                    ),
                )
                venue = cursor.fetchone()
                if not venue:
                    raise HTTPException(status_code=500, detail="Venue could not be created.")
                for display_order, image_url in enumerate(payload.photo_urls):
                    cursor.execute(
                        "INSERT INTO venue_photos (id, venue_id, image_url, display_order) VALUES (%s, %s, %s, %s)",
                        (uuid4(), venue_id, str(image_url), display_order),
                    )
    except HTTPException:
        raise
    except psycopg.errors.ForeignKeyViolation as error:
        raise HTTPException(status_code=400, detail="The selected sport does not exist.") from error
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Venue registration is temporarily unavailable.") from error

    return {"venue_id": str(venue[0]), "name": venue[1], "sport_id": venue[2]}


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