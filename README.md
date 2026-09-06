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

## Current flows

- `POST /api/auth/signup` creates a player or court-manager account with a securely hashed password.
- `POST /api/auth/login` verifies the password and reports whether profile completion is still required.
- `PUT /api/users/{user_id}/profile` saves the full name and optional profile-picture URL.
- `GET /venues/new` provides the court-manager registration form. It loads the sports dropdown from `GET /api/sports` and submits to `POST /api/venues`.

The browser stores the returned user ID locally for this first vertical slice. Before production, replace that temporary client-side identity with signed sessions or JWTs, add Google OAuth verification, validate uploaded images, and add Stripe checkout/webhooks.