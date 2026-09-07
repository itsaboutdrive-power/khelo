-- Khelo PostgreSQL schema plan
-- Lookup data: sports; identities: users; inventory: venues and venue_photos;
-- bookable time: availability_blocks and bookings; payment records: payments;
-- player activity: matches.
DROP DATABASE khelo;
CREATE DATABASE khelo;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE user_role AS ENUM ('player', 'court_manager');
CREATE TYPE booking_status AS ENUM ('pending', 'confirmed', 'cancelled', 'completed');
CREATE TYPE payment_status AS ENUM ('pending', 'paid', 'refunded', 'failed');

CREATE TABLE sports (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (char_length(trim(name)) > 0)
);

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email CITEXT NOT NULL UNIQUE,
    password_hash TEXT,
    google_subject TEXT UNIQUE,
    full_name TEXT,
    profile_picture_url TEXT,
    role user_role NOT NULL DEFAULT 'player',
    profile_completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (password_hash IS NOT NULL OR google_subject IS NOT NULL)
);

CREATE TABLE venues (
    id UUID PRIMARY KEY,
    manager_id UUID NOT NULL REFERENCES users(id),
    sport_id BIGINT NOT NULL REFERENCES sports(id),
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    google_maps_url TEXT NOT NULL,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    slot_duration_minutes SMALLINT NOT NULL CHECK (slot_duration_minutes BETWEEN 15 AND 240),
    opens_at TIME NOT NULL,
    closes_at TIME NOT NULL,
    booking_price_cents INTEGER NOT NULL CHECK (booking_price_cents >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    booking_id BIGINT NOT NULL DEFAULT -1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (closes_at > opens_at)
);

CREATE TABLE venue_photos (
    id UUID PRIMARY KEY,
    venue_id UUID NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    display_order SMALLINT NOT NULL DEFAULT 0 CHECK (display_order >= 0)
);

CREATE TABLE availability_blocks (
    id UUID PRIMARY KEY,
    venue_id UUID NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    reason TEXT,
    CHECK (ends_at > starts_at)
);

CREATE TABLE bookings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id UUID NOT NULL REFERENCES venues(id),
    player_id UUID NOT NULL REFERENCES users(id),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status booking_status NOT NULL DEFAULT 'pending',
    total_price_cents INTEGER NOT NULL CHECK (total_price_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at)
);

CREATE TABLE payments (
    id UUID PRIMARY KEY,
    booking_id BIGINT NOT NULL UNIQUE REFERENCES bookings(id),
    stripe_payment_intent_id TEXT NOT NULL UNIQUE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    status payment_status NOT NULL DEFAULT 'pending',
    paid_at TIMESTAMPTZ
);

CREATE TABLE matches (
    id UUID PRIMARY KEY,
    player_id UUID NOT NULL REFERENCES users(id),
    opponent_name TEXT NOT NULL,
    final_score TEXT NOT NULL,
    played_on DATE NOT NULL,
    booking_id BIGINT REFERENCES bookings(id) ON DELETE SET NULL
);

CREATE INDEX venues_sport_id_idx ON venues(sport_id);
CREATE INDEX bookings_venue_time_idx ON bookings(venue_id, starts_at, ends_at);
CREATE INDEX availability_blocks_venue_time_idx ON availability_blocks(venue_id, starts_at, ends_at);
CREATE INDEX matches_player_date_idx ON matches(player_id, played_on DESC);

INSERT INTO sports (name) VALUES
    ('Badminton'),
    ('Basketball'),
    ('Box Cricket'),
    ('Football'),
    ('Pickleball'),
    ('Squash'),
    ('Table Tennis'),
    ('Tennis'),
    ('Volleyball')
ON CONFLICT (name) DO NOTHING;