# Khelo

Starter application for booking sports courts and grounds.

## Database plan

- `sports` is the dedicated lookup table for all sport names.
- `venues.sport_id` references `sports.id`, so venue registration can use a validated dropdown backed by `GET /api/sports`.
- `users` supports player and court-manager roles, email/password authentication, and Google OAuth identities.
- `venues`, `venue_photos`, `availability_blocks`, and `bookings` provide the core court discovery and availability model.
- `payments` stores Stripe payment-intent state; `matches` stores player match history.

## Run locally

1. Create a PostgreSQL database named `khelo` and run `schema.sql` against it.
2. Create `.env` from `.env.example` and update `DATABASE_URL`.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Start the API with `python -m uvicorn main:app --reload`.
5. Open `http://127.0.0.1:8000` for the login page, or `http://127.0.0.1:8000/docs` for the API documentation.

The login form is currently visual only. Implement password hashing, OAuth verification, sessions, and Stripe webhooks before accepting real account or payment traffic.