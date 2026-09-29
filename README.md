# EVE Healthcare — diagnostic bookings API

Backend for booking a diagnostic test at a centre and paying through a simulated provider.

**For reviewers:** use **Docker** below. You do **not** need to install PostgreSQL or Redis on your machine — they run in containers. Interactive docs: [Swagger UI](http://localhost:8000/docs/).

[![CI](https://github.com/shrutisharma91/EVE-HEALTHCARE-ASSIGNMENT/actions/workflows/ci.yml/badge.svg)](https://github.com/shrutisharma91/EVE-HEALTHCARE-ASSIGNMENT/actions/workflows/ci.yml)

---

## 1. Setup (Docker — recommended)

### What you need

- Docker Desktop running (Engine must be started)
- A terminal in the project folder

### Steps

```bash
# 1. Copy env file (once), then set a private webhook secret
cp .env.example .env
# Edit .env and replace WEBHOOK_SECRET with your own value.
# The placeholder from .env.example is rejected when DEBUG=False.

# 2. Start everything (web + Postgres + Redis + Celery worker)
docker compose up --build -d

# 3. Wait ~30–60 seconds, then check health
curl http://localhost:8000/health/

# 4. Load demo centres, tests, and users (safe to run again)
docker compose exec web python manage.py seed_data
```

**Healthy response:**

```json
{ "status": "ok", "db": "ok", "cache": "ok" }
```

Open Swagger: **http://localhost:8000/docs/**  
(Do not use `http://localhost:8000/` alone — there is no page on `/`, so you will see `404 NOT_FOUND`.)

### Login accounts (after seed)

| Role | Email | Password |
|---|---|---|
| Patient | `demo@eve.test` | `Patient#Host2026` |
| Admin | `admin@eve.test` | `Clinic#Host2026` |

### Port already in use?

If host ports `5432` or `6379` are taken, set in `.env` before `up`:

```env
POSTGRES_PUBLISH_PORT=5434
REDIS_PUBLISH_PORT=6380
```

Containers still talk to each other as `db` and `redis`. The API stays on **port 8000**.

### Stop

```bash
docker compose down
```

---

## 2. Manual test workflow (Swagger)

Goal: login → pick a centre/test → book → pay → see booking `CONFIRMED`.

**Important:** never copy UUIDs from the grey/green “Example Value” panels (those like `3fa85f64-…` are fake). Only copy ids from the **Server response** after you click **Execute**.

### Step A — Authorize

1. `POST /auth/login/` with:

```json
{ "email": "demo@eve.test", "password": "Patient#Host2026" }
```

2. Copy `access` from the response.  
3. Click **Authorize** → paste the token → Authorize → Close.

### Step B — Get real centre and test ids

1. `GET /centres/?city=Guwahati` → Execute → copy a centre `"id"` → call it `CENTRE_ID`.  
2. `GET /centres/{CENTRE_ID}/` → Execute → in `tests`, pick CBC (or any row) → copy that test `"id"` → `TEST_ID`. Note `"price"`.

### Step C — Create a booking

`POST /bookings/` body (change the date if needed; must be **future**, within 90 days, **07:00–20:00 IST**):

```json
{
  "centre_id": "<CENTRE_ID>",
  "test_id": "<TEST_ID>",
  "appointment_at": "2026-10-15T10:00:00+05:30"
}
```

**Success:** `201`, `"status": "PENDING"`, `"amount"` matches the centre price.  
Copy response `"id"` → this is `BOOKING_ID` (the only id that works for payment).

### Step D — Pay

`POST /payments/`:

1. Header **`Idempotency-Key`**: type any unique string, e.g. `pay-001` (shown under Parameters).  
2. Body:

```json
{
  "booking_id": "<BOOKING_ID>",
  "simulate_outcome": "SUCCESS"
}
```

**Success:** `201`, payment `"status": "SUCCESS"`, `"booking_status": "CONFIRMED"`.

### Step E — Confirm

`GET /bookings/{BOOKING_ID}/` → **Success:** `"status": "CONFIRMED"`.

Optional: call pay again with the **same** `Idempotency-Key` → `200` and the **same** payment id (idempotent retry).

### Admin vs patient

Same URLs for everyone. Admin can create/update centres and tests; a patient gets `403` on those writes. Patients only see their own bookings/payments (someone else’s id → `404`).

Full click-by-click checklist: [docs/MANUAL_TEST_WORKFLOW.md](docs/MANUAL_TEST_WORKFLOW.md).

---

## 3. Automated tests (optional for reviewers)

```bash
# Unit / integration (needs Postgres + Redis reachable as in .env / local services)
make test

# Live HTTP against the running Compose stack
pip install -r requirements-dev.txt
make smoke
```

- `make test` — pytest, coverage ≥ 90%  
- `make smoke` — black-box cases; report at [docs/API_TEST_REPORT.md](docs/API_TEST_REPORT.md)  
- Plan: [docs/API_TEST_PLAN.md](docs/API_TEST_PLAN.md)  
- Postman: `postman/EVE_Healthcare.postman_collection.json` + `postman/local.postman_environment.json`

---

## 4. What this project covers

### Assignment requirements

| Requirement | Done |
|---|---|
| Signup / login / JWT | Yes |
| Centres, tests, prices | Yes |
| Bookings (`PENDING` / `CONFIRMED` / `FAILED` / `CANCELLED`) | Yes |
| Simulated `POST /payments/` | Yes |
| Idempotent `POST /payments/webhook/` | Yes |
| Edge cases (auth, duplicates, invalid ids, failed pay) | Yes |
| PostgreSQL | Yes (Compose service `db`) |

### Optional bonuses (also implemented)

Redis caching · Celery webhooks with retries · Docker Compose · Swagger/OpenAPI · pytest (≥90% coverage) · structured JSON logs · pagination · rate limiting

---

## 5. Useful links while running

| URL | Purpose |
|---|---|
| http://localhost:8000/health/ | DB + Redis check |
| http://localhost:8000/docs/ | Swagger — try the API |
| http://localhost:8000/redoc/ | ReDoc |
| http://localhost:8000/schema/ | OpenAPI JSON/YAML |

---

## Tech stack & why

| Piece | Why it is here |
|---|---|
| Django 5 + DRF | Models, admin, and JSON APIs in one place. Views stay thin. |
| PostgreSQL 16 | Partial unique indexes and row locks for idempotency. |
| `djangorestframework-simplejwt` | Access (30 min) + rotating refresh (7 days) with blacklist. |
| `drf-spectacular` | OpenAPI 3, Swagger, ReDoc from the same serializers. |
| Redis 7 | Centre-list cache, throttle counters, Celery broker. |
| Celery 5 | Webhooks accept fast; worker applies payment and retries DB blips. |
| `django-environ` | Config from environment. `DEBUG` defaults off. |
| `structlog` | JSON logs with `request_id`. |
| pytest, factory-boy, freezegun | Tests on PostgreSQL, including time-based rules. |
| Docker Compose + GitHub Actions | Same stack for local review and CI. |

Routes are unversioned (`/bookings/`, `/payments/`) to match the assignment.

## Architecture

Apps: `accounts` (identity), `catalog` (centres/prices), `bookings` (reservations + state machine), `payments` (attempts + webhook ledger), `core` (errors, pagination, health).

Flow: view → serializer → service → model. State changes run inside `transaction.atomic()` with row locks.

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB
    participant Simulator
    participant Worker
    Client->>API: POST /bookings/
    API->>DB: lock centre and offering, insert PENDING
    Note over DB: amount copied from CentreTest.price
    Client->>API: POST /payments/ + Idempotency-Key
    API->>DB: lock booking, insert Payment INITIATED
    alt simulate_outcome SUCCESS or FAILED
        API->>Simulator: process(payment)
        API->>DB: apply_payment_result
        API-->>Client: 201 settled payment and booking status
    else simulate_outcome PENDING
        API-->>Client: 201 payment INITIATED, booking still PENDING
    end
    Client->>API: POST /payments/webhook/ (signed)
    API->>DB: insert WebhookEvent (event_id unique)
    API->>Worker: process_webhook_event
    API-->>Client: 200 accepted
    Worker->>DB: lock event, booking, payment
    Worker->>DB: apply_payment_result (same function)
```

`simulate_outcome: "PENDING"` leaves payment `INITIATED` until a signed webhook settles it (same idea as a real gateway). `SUCCESS` / `FAILED` settle inline.

## Database design

Money is `Decimal(10, 2)`. Currency defaults to `INR`. Datetimes UTC in DB; business hours in `Asia/Kolkata`.

```mermaid
erDiagram
    User ||--o{ Booking : places
    User ||--o{ Payment : owns
    DiagnosticCentre ||--o{ CentreTest : offers
    DiagnosticTest ||--o{ CentreTest : "priced at"
    DiagnosticCentre ||--o{ Booking : hosts
    DiagnosticTest ||--o{ Booking : "booked as"
    Booking ||--o{ Payment : attempts
    Payment ||--o{ WebhookEvent : "matched by reference"
    User {
        uuid id PK
        string email UK
        string full_name
        string phone
    }
    DiagnosticCentre {
        uuid id PK
        string name
        string city
        string pincode
        bool is_active
    }
    DiagnosticTest {
        uuid id PK
        string code UK
        string sample_type
        bool is_active
    }
    CentreTest {
        uuid id PK
        decimal price
        bool is_available
    }
    Booking {
        uuid id PK
        datetime appointment_at
        decimal amount
        string status
    }
    Payment {
        uuid id PK
        decimal amount
        string currency
        string status
        string provider_reference UK
        string idempotency_key
    }
    WebhookEvent {
        int id PK
        string event_id UK
        json payload
        string processing_status
        int attempts
    }
```

- **Price snapshot** — `Booking.amount` copied from `CentreTest.price` at create time.  
- **Active-booking uniqueness** — partial unique index on pending/confirmed slots.  
- **One SUCCESS payment per booking** — partial unique index.  
- **Idempotency-Key** unique per user; webhook `event_id` unique.

## Booking state machine

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> CONFIRMED: payment success
    PENDING --> FAILED: payment failed
    PENDING --> CANCELLED: user cancels
    CONFIRMED --> CANCELLED: appointment more than 2 hours away
    FAILED --> [*]
    CANCELLED --> [*]
```

`FAILED` / `CANCELLED` are terminal. Cancel confirmed inside 2 hours → `409 CANCELLATION_WINDOW_CLOSED`.

## API reference

Errors use one envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input.",
    "details": { "appointment_at": ["Must be in the future."] }
  }
}
```

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/auth/signup/` | public | 201 + tokens. Duplicate email 409. |
| POST | `/auth/login/` | public | Access + refresh. |
| POST | `/auth/token/refresh/` | public | Rotates refresh; old one blacklisted. |
| GET | `/auth/me/` | JWT | Profile. |
| GET | `/centres/` | public | `?city=`, `?test_code=`, `?search=`. Cached. |
| GET | `/centres/{id}/` | public | Centre + tests + prices. |
| GET | `/centres/{id}/tests/` | public | Offerings. |
| GET | `/tests/` | public | Catalogue. |
| POST, PATCH, DELETE | `/centres/…` | staff | Soft-delete on DELETE. |
| POST, PATCH, DELETE | `/centres/{id}/tests/…` | staff | Prices / availability. |
| POST | `/bookings/` | JWT | Amount is server-side. |
| GET | `/bookings/` | JWT | Own rows (staff: all). |
| GET | `/bookings/{id}/` | JWT | Own or 404. |
| POST | `/bookings/{id}/cancel/` | JWT | Optional `reason`. |
| POST | `/payments/` | JWT | **Header `Idempotency-Key` required.** |
| GET | `/payments/{id}/` | JWT | Own payment or 404. |
| GET | `/bookings/{id}/payments/` | JWT | Attempts for that booking. |
| POST | `/payments/webhook/` | HMAC | No JWT. |
| GET | `/health/` | public | `db` + `cache`. |

Throttles: login/signup `5/minute`, user `100/minute`, anon `30/minute`. Health and webhook are exempt → `429 THROTTLED`.

### Curl examples

```bash
# Login
curl -s -X POST http://localhost:8000/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@eve.test","password":"Patient#Host2026"}'

# Centres
curl -s 'http://localhost:8000/centres/?city=Guwahati'

# Book (replace TOKEN and ids)
curl -s -X POST http://localhost:8000/bookings/ \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"centre_id":"<centre-uuid>","test_id":"<test-uuid>","appointment_at":"2026-10-15T10:00:00+05:30"}'

# Pay
curl -s -X POST http://localhost:8000/payments/ \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: pay-reviewer-001' \
  -d '{"booking_id":"<booking-uuid>","simulate_outcome":"SUCCESS"}'

# Webhook helper (after PENDING payment — amount must match the payment row)
python scripts/simulate_webhook.py \
  --provider-reference <provider_reference> \
  --amount <amount_from_payment> \
  --times 3
```

Webhook HMAC is Stripe-style: `sha256=HMAC(WEBHOOK_SECRET, "{timestamp}.{raw_body}")`. Timestamps more than five minutes past **or future** are rejected.

## Idempotency & consistency

1. **`Idempotency-Key`** — same user + key returns the original payment; different booking → `422`.  
2. **`WebhookEvent.event_id`** — duplicates return `{"status":"duplicate"}`; a duplicate while still `RECEIVED` re-queues the worker.  
3. **`select_for_update`** — booking/payment/event locked in a fixed order.  
4. **Partial unique indexes** — no double active booking; no second SUCCESS payment.  
5. **Order-safe apply** — late failure after success ignored; success after cancel keeps booking cancelled and logs refund. Late success after the booking left PENDING settles the payment only (or flags `duplicate_gateway_success_refund_required` if a SUCCESS already exists) and never corrupts booking state.

## Edge cases handled

| Situation | Result |
|---|---|
| Duplicate email | 409 `EMAIL_ALREADY_REGISTERED` |
| Bad login | 401 `INVALID_CREDENTIALS` (same message either way) |
| Other user’s booking/payment | 404 `NOT_FOUND` |
| Missing `Idempotency-Key` | 400 `IDEMPOTENCY_KEY_REQUIRED` |
| Pay already confirmed | 409 `BOOKING_ALREADY_PAID` |
| Duplicate webhook `event_id` | 200 `duplicate` |
| Bad/stale webhook signature | 401 `INVALID_WEBHOOK_SIGNATURE` |
| Too many logins | 429 `THROTTLED` |

## Local run without Docker (optional)

Needs Python 3.12, PostgreSQL 16, and Redis 7 on the host. Prefer Docker if you can.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements-dev.txt
# create DB user/db eve / password eve, then:
```

```bash
export DJANGO_SETTINGS_MODULE=config.settings.dev
export SECRET_KEY=dev-secret-key-for-local-only-not-production
export DATABASE_URL=postgres://eve:eve@127.0.0.1:5432/eve
export REDIS_URL=redis://127.0.0.1:6379/0
export WEBHOOK_SECRET=dev-webhook-secret
python manage.py migrate
python manage.py seed_data
python manage.py runserver
# other terminal:
celery -A config worker --loglevel=info
```

PowerShell: `$env:NAME="value"` instead of `export`.

## Assumptions

- One test per booking.  
- Client cannot set amount; server snapshots price.  
- Centres open 07:00–20:00 IST daily; no slot capacity limit.  
- Staff manage catalogue; others read active centres.  
- Webhook finds payment by `provider_reference`; it never creates a booking.  
- Currency is INR. Confirmed cancel logs a refund intent only.

## What I'd improve with more time

Slot capacity · real Razorpay adapter · refund flow · outbox · `/api/v1` · notifications · Sentry/metrics · load tests on payment locks.

## Project structure

```text
eve-healthcare/
├── config/                  # settings, urls, celery
├── apps/
│   ├── accounts/            # User, signup, login, me
│   ├── catalog/             # centres, tests, prices, seed
│   ├── bookings/            # booking + state machine
│   ├── payments/            # simulator, webhook, Celery
│   └── core/                # errors, pagination, health
├── tests/
├── docs/                    # manual workflow, API plan, smoke report
├── postman/
├── scripts/api_smoke_test.py
├── scripts/simulate_webhook.py
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── .env.example
├── requirements.txt
└── requirements-dev.txt
```
