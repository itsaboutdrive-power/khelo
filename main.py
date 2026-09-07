from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import os
from pathlib import Path
import secrets
from time import monotonic
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, HttpUrl, field_validator
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Khelo API", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
VENUE_POLL_INTERVAL_SECONDS = 10
last_venue_poll: dict[UUID, float] = {}
RATING_POLL_INTERVAL_SECONDS = 10
rating_cache: dict[UUID, tuple[float, UUID, dict]] = {}


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: str = "player"
    full_name: str = Field(min_length=2, max_length=120)
    profile_picture_url: HttpUrl | None = None

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


def google_maps_request(endpoint: str, parameters: dict[str, str]) -> dict:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Google Maps is not configured.")

    url = f"https://maps.googleapis.com/maps/api/{endpoint}?{urlencode({**parameters, 'key': api_key})}"
    try:
        with urlopen(url, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as error:
        raise HTTPException(status_code=503, detail="Location service is temporarily unavailable.") from error

    import json

    result = json.loads(payload)
    if result.get("status") != "OK":
        raise HTTPException(status_code=400, detail="Google Maps could not resolve the requested location.")
    return result


def resolve_origin(latitude: float | None, longitude: float | None, location: str | None) -> tuple[float, float]:
    if latitude is not None and longitude is not None:
        return latitude, longitude
    if not location:
        raise HTTPException(status_code=422, detail="Provide latitude/longitude or a location.")

    result = google_maps_request("geocode/json", {"address": location})
    coordinates = result["results"][0]["geometry"]["location"]
    return coordinates["lat"], coordinates["lng"]


def get_distances(origin: tuple[float, float], venues: list[tuple]) -> dict[UUID, int]:
    destinations = "|".join(f"{venue[5]},{venue[6]}" for venue in venues)
    result = google_maps_request(
        "distancematrix/json",
        {"origins": f"{origin[0]},{origin[1]}", "destinations": destinations, "mode": "driving"},
    )
    elements = result["rows"][0]["elements"]
    return {
        venue[0]: element["distance"]["value"]
        for venue, element in zip(venues, elements)
        if element.get("status") == "OK"
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


@app.get("/api/venues/{venue_id}/ratings")
def get_venue_ratings(venue_id: UUID, user_id: UUID) -> dict:
    """Return venue ratings, reusing the user's previous result during the cooldown."""
    now = monotonic()
    cached = rating_cache.get(user_id)
    if cached and now - cached[0] < RATING_POLL_INTERVAL_SECONDS:
        return cached[2]

    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="User not found.")

                cursor.execute(
                    """
                    SELECT id, rating_text, rating, user_id, venue_id,
                           reply_ids, likes, dislikes, created_at
                    FROM ratings
                    WHERE venue_id = %s
                    ORDER BY (likes + cardinality(reply_ids) - dislikes) DESC,
                             created_at DESC, id DESC
                    """,
                    (venue_id,),
                )
                ratings = [
                    {
                        "rating_id": rating[0],
                        "rating_text": rating[1],
                        "rating": rating[2],
                        "user_id": str(rating[3]),
                        "venue_id": str(rating[4]),
                        "reply_ids": rating[5],
                        "likes": rating[6],
                        "dislikes": rating[7],
                        "score": rating[6] + len(rating[5]) - rating[7],
                        "created_at": rating[8].isoformat(),
                    }
                    for rating in cursor.fetchall()
                ]
    except HTTPException:
        raise
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Ratings are temporarily unavailable.") from error

    response = {
        "venue_id": str(venue_id),
        "next_request_after_seconds": RATING_POLL_INTERVAL_SECONDS,
        "ratings": ratings,
    }
    rating_cache[user_id] = (now, venue_id, response)
    return response


@app.get("/api/venues/discover")
def discover_venues(
    player_id: UUID,
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    location: str | None = Query(default=None, min_length=2, max_length=250),
    sport_ids: list[int] | None = Query(default=None),
    max_distance_km: float = Query(default=10, gt=0, le=100),
    sort_by_price: Literal["low_to_high", "high_to_low"] | None = None,
) -> dict:
    """Poll currently available courts, limited to one request per player every 10 seconds."""
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=422, detail="Latitude and longitude must be sent together.")

    now = monotonic()
    previous_poll = last_venue_poll.get(player_id)
    if previous_poll is not None and now - previous_poll < VENUE_POLL_INTERVAL_SECONDS:
        retry_after = max(1, int(VENUE_POLL_INTERVAL_SECONDS - (now - previous_poll)))
        raise HTTPException(
            status_code=429,
            detail="Venue polling is limited to once every 10 seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    last_venue_poll[player_id] = now
    origin = resolve_origin(latitude, longitude, location)
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT role FROM users WHERE id = %s", (player_id,))
                player = cursor.fetchone()
                if not player or player[0] != "player":
                    raise HTTPException(status_code=403, detail="Only players can discover venues.")

                query = """
                    SELECT v.id, v.name, s.name, v.address, v.google_maps_url,
                           v.latitude, v.longitude, v.slot_duration_minutes,
                           v.booking_price_cents, v.currency, v.opens_at, v.closes_at
                    FROM venues AS v
                    JOIN sports AS s ON s.id = v.sport_id
                    WHERE v.is_active = true
                      AND v.latitude IS NOT NULL AND v.longitude IS NOT NULL
                      AND CURRENT_TIME >= v.opens_at AND CURRENT_TIME < v.closes_at
                      AND (
                          v.booking_id = -1
                          OR NOT EXISTS (
                              SELECT 1 FROM bookings AS b
                              WHERE b.id = v.booking_id
                          )
                          OR EXISTS (
                              SELECT 1 FROM bookings AS b
                              WHERE b.id = v.booking_id
                                AND (now() < b.starts_at OR now() >= b.ends_at)
                          )
                      )
                """
                parameters: list[object] = []
                if sport_ids:
                    query += " AND v.sport_id = ANY(%s)"
                    parameters.append(sport_ids)
                query += " ORDER BY v.id LIMIT 25"
                cursor.execute(query, parameters)
                venues = cursor.fetchall()
    except HTTPException:
        raise
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Venue discovery is temporarily unavailable.") from error

    distances = get_distances(origin, venues)
    maximum_distance_meters = int(max_distance_km * 1000)
    results = [
        {
            "venue_id": str(venue[0]), "name": venue[1], "sport": venue[2],
            "address": venue[3], "google_maps_url": venue[4],
            "distance_meters": distances[venue[0]], "slot_duration_minutes": venue[7],
            "booking_price_cents": venue[8], "currency": venue[9],
            "opens_at": venue[10].isoformat(), "closes_at": venue[11].isoformat(),
        }
        for venue in venues
        if venue[0] in distances and distances[venue[0]] <= maximum_distance_meters
    ]
    if sort_by_price == "low_to_high":
        results.sort(key=lambda venue: venue["booking_price_cents"])
    elif sort_by_price == "high_to_low":
        results.sort(key=lambda venue: venue["booking_price_cents"], reverse=True)
    else:
        results.sort(key=lambda venue: venue["distance_meters"])

    return {
        "max_distance_km": max_distance_km,
        "next_poll_after_seconds": VENUE_POLL_INTERVAL_SECONDS,
        "venues": results,
    }


@app.post("/api/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest) -> dict:
    user_id = uuid4()
    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        id, email, password_hash, role, full_name,
                        profile_picture_url, profile_completed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING email, role, full_name
                    """,
                    (
                        user_id,
                        payload.email,
                        hash_password(payload.password),
                        payload.role,
                        payload.full_name.strip(),
                        str(payload.profile_picture_url) if payload.profile_picture_url else None,
                        datetime.now(timezone.utc),
                    ),
                )
                created_user = cursor.fetchone()
                if not created_user:
                    raise HTTPException(status_code=500, detail="Account could not be created.")
                email, role, full_name = created_user
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from error
    except (RuntimeError, psycopg.Error) as error:
        raise HTTPException(status_code=503, detail="Account creation is temporarily unavailable.") from error

    return user_response(user_id, email, role, full_name)


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