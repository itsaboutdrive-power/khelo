# Khelo

Starter application for booking sports courts and grounds.

## Database plan

- `sports` is the dedicated lookup table for all sport names.
- `venues.sport_id` references `sports.id`, so venue registration can use a validated dropdown backed by `GET /api/sports`.
- `users` supports player and court-manager roles, email/password authentication, and Google OAuth identities.
- `venues`, `venue_photos`, `availability_blocks`, and `bookings` provide the core court discovery and availability model.
- `payments` stores Stripe payment-intent state; `matches` stores player match history.
- `ratings` stores venue reviews, scores, likes, dislikes, and reply ID arrays; `venues.rating_ids` mirrors the rating IDs for each venue.
- `venues.booking_id` is the active-booking pointer. Its default value of `-1` means the venue is free. Discovery treats a missing booking row as stale/free; otherwise it checks the referenced booking's time range.

## Run locally

1. Create a PostgreSQL database named `khelo` and run `schema.sql` against it.
2. Create `.env` from `.env.example` and update `DATABASE_URL`.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Start the API with `python -m uvicorn main:app --reload`.
5. Open `http://127.0.0.1:8000` for the login page, or `http://127.0.0.1:8000/docs` for the API documentation.

## Current flows

- `POST /api/auth/signup` creates a player or court-manager account with a securely hashed password.
- `POST /api/auth/login` verifies the password and reports whether profile completion is still required.
- `PUT /api/users/{user_id}/profile` saves the full name and optional profile-picture URL.
- `GET /venues/new` provides the court-manager registration form. It loads the sports dropdown from `GET /api/sports` and submits to `POST /api/venues`.
- `GET /api/venues/discover` lists courts currently free for a player. Send `player_id`, either `latitude` and `longitude` or a `location` string, and optionally repeated `sport_ids`, `max_distance_km` (default `10`), and `sort_by_price` (`low_to_high` or `high_to_low`). It returns distance-sorted venues by default and accepts one request per player every 10 seconds.
- `GET /api/venues/{venue_id}/ratings?user_id=USER_UUID` lists ratings for a venue in descending order of `likes + reply count - dislikes`. Each user receives the previous response for requests made within 10 seconds. The current cache is process-local; use a shared Redis cache before running multiple API workers.
- Player accounts are directed to `/static/player-venues.html`, which requests browser location and polls the discovery endpoint every 10 seconds. Sports and price choices apply to the next scheduled poll; a `429` response means the user must wait for the server's `Retry-After` value.

Venue discovery needs a Google Maps API key with Geocoding API and Distance Matrix API enabled. Set `GOOGLE_MAPS_API_KEY` in `.env`. For example:

```text
/api/venues/discover?player_id=USER_UUID&latitude=19.0760&longitude=72.8777&sport_ids=1&sport_ids=8&sort_by_price=low_to_high
```

The browser stores the returned user ID locally for this first vertical slice. Before production, replace that temporary client-side identity with signed sessions or JWTs, add Google OAuth verification, validate uploaded images, and add Stripe checkout/webhooks.

`schema.sql` now uses integer booking IDs so that `venues.booking_id` can use `-1` as its free sentinel. If you already created the earlier UUID-based `bookings` table, recreate this development database and run the updated schema; PostgreSQL cannot safely convert existing UUID booking IDs to this new format automatically.