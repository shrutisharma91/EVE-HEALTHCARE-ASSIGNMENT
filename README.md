# EVE Healthcare — diagnostic bookings API

Backend for booking a diagnostic test at a centre and paying for it through a simulated provider. Bookings move through an explicit state machine, prices are snapshotted at booking time, and both client retries and provider webhooks are idempotent. Interactive docs: [Swagger UI](http://localhost:8000/docs/), [ReDoc](http://localhost:8000/redoc/), [OpenAPI schema](http://localhost:8000/schema/).

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF)](./.github/workflows/ci.yml)
![coverage](https://img.shields.io/badge/coverage-%E2%89%A590%25-brightgreen)

## Quick start

### Docker

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health/
```

The API listens on port 8000. `SEED_DATA=true` in `.env.example` loads centres, tests, and two users on boot. If port 5432 or 6379 is already taken on the host, set `POSTGRES_PUBLISH_PORT` and `REDIS_PUBLISH_PORT` in `.env` before `up`. Containers still talk to each other as `db:5432` and `redis:6379`.

Demo logins after seed:

| Email | Password | Role |
|---|---|---|
| `admin@eve.test` | `Clinic#Host2026` | staff |
| `demo@eve.test` | `Patient#Host2026` | patient |

### Local, without Docker

Requires Python 3.12, PostgreSQL 16, and Redis 7. SQLite is not used.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
createdb -U postgres eve    # or create user eve / password eve / database eve
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
celery -A config worker --loglevel=info
```

On PowerShell, set those variables with `$env:NAME="value"` instead of `export`.

## Tech stack & why

| Piece | Why it is here |
|---|---|
| Django 5 + DRF | One framework for models, admin, and JSON APIs. Views stay thin. |
| PostgreSQL 16 | Partial unique indexes and row locks, which the idempotency rules depend on. |
| `djangorestframework-simplejwt` | Access tokens (30 min) and rotating refresh tokens (7 days) with a blacklist. |
| `drf-spectacular` | OpenAPI 3, Swagger, and ReDoc from the same serializers the API uses. |
| Redis 7 | Shared cache for centre lists and the DRF throttle counters. Also the Celery broker. |
| Celery 5 | Webhooks return as soon as the event is stored. Retries cover database blips. |
| `django-environ` | Secrets and lifetimes come from the environment. `DEBUG` defaults to off. |
| `structlog` | One JSON line per event, with the request id on every line. |
| pytest, factory-boy, freezegun | Tests run on PostgreSQL, including time-dependent auth and cancellation rules. |
| ruff + pre-commit | Lint and format in CI and locally. |
| Docker Compose + GitHub Actions | A fresh clone boots the same Postgres and Redis the tests use. |

Routes are unversioned (`/bookings/`, `/payments/`) so they match the assignment. A `/api/v1` prefix is the natural next step once a client depends on the shape.

## Architecture

Each app owns one area. `accounts` is identity, `catalog` is centres and prices, `bookings` is the reservation and its state machine, `payments` is attempts plus the webhook ledger, and `core` is the error envelope, pagination, permissions, request ids, and the health check.

A request goes view → serializer → service → model. Serializers check input and shape output. Services hold the rules and wrap every state change in `transaction.atomic()`, locking the rows they read and then write. Reused queries live in `selectors.py`.

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

`PaymentSimulator.process(payment)` returns a small result object. `POST /payments/` calls it inline for `SUCCESS` and `FAILED`. `simulate_outcome: "PENDING"` does not settle anything: the payment stays `INITIATED` and the booking stays `PENDING` until a signed webhook calls `apply_payment_result`. That is the same split a gateway such as Razorpay uses. The simulator class can be swapped for a real provider later; the booking update still goes through `apply_payment_result`.

## Database design

Money is `Decimal(10, 2)`. Currency on a payment defaults to `INR`. Datetimes are stored in UTC (`USE_TZ=True`) and displayed in `Asia/Kolkata`.

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

- **UUIDs** on `User`, centres, tests, `Booking`, and `Payment`. Booking and payment ids are not enumerable, so guessing the next id is not a way to probe other people's rows.
- **Price snapshot.** `Booking.amount` is copied from `CentreTest.price` inside the create transaction. A later price change does not rewrite existing bookings.
- **CentreTest** is the through table. The catalogue says what a test is; each centre chooses whether it offers that test and at what price. Unique on `(centre, test)`, and `price > 0`.
- **Active-booking uniqueness.** Partial unique index on `(user, centre, test, appointment_at)` where status is `PENDING` or `CONFIRMED`. A cancelled or failed row does not block a new attempt. The service turns `IntegrityError` into `409 DUPLICATE_BOOKING`.
- **One successful charge.** Partial unique index on `Payment.booking` where `status = SUCCESS`. Many `FAILED` attempts are allowed. A second success cannot be inserted.
- **Idempotency key.** Unique on `(user, idempotency_key)`, so a client retry returns the original payment.
- **Webhook ledger.** `WebhookEvent.event_id` is unique. The raw body is stored. Processing status, attempt count, and the last error make retries and audits visible. A webhook never inserts a booking or a payment.

Other constraints: centre `(name, city)` unique, `city` indexed, pincode is 6 digits, booking indexes `(user, status)` and `(centre, appointment_at)`, booking and payment amounts must be `> 0`. Foreign keys on bookings and payments use `PROTECT` so history cannot be deleted out from under a payment.

## Booking state machine

Status changes happen only in `bookings/state_machine.py`. Creating a booking leaves the default `PENDING`. Everything else calls `transition()`.

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> CONFIRMED: payment success
    PENDING --> FAILED: payment failed
    PENDING --> CANCELLED: user cancels
    CONFIRMED --> CANCELLED: appointment is more than 2 hours away
    FAILED --> [*]
    CANCELLED --> [*]
```

`FAILED` and `CANCELLED` are terminal. The user creates a new booking. Cancelling a `CONFIRMED` booking at or inside the two-hour window returns `409 CANCELLATION_WINDOW_CLOSED`. A confirmed cancellation further out is allowed and logs that a refund would be triggered. Any other jump returns `409 INVALID_STATE_TRANSITION`.

## API reference

JSON, trailing slashes, plural nouns. List endpoints use page number pagination (`page_size` 10, up to 100). Errors share one envelope:

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
| POST | `/auth/signup/` | public | 201 user + tokens. Duplicate email 409. |
| POST | `/auth/login/` | public | Access + refresh. Bad credentials 401. |
| POST | `/auth/token/refresh/` | public | Rotates and blacklists the old refresh token. |
| GET | `/auth/me/` | JWT | Current profile. |
| GET | `/centres/` | public | Active centres. `?city=`, `?test_code=`, `?search=`. Cached 5 minutes. |
| GET | `/centres/{id}/` | public | Centre plus offered tests and prices. |
| GET | `/centres/{id}/tests/` | public | Offerings and prices. |
| GET | `/tests/` | public | Catalogue. `?search=`. |
| POST, PATCH | `/centres/`, `/centres/{id}/` | staff | DELETE sets `is_active=false`. |
| POST | `/centres/{id}/tests/` | staff | Add a test at a price. |
| PATCH, DELETE | `/centres/{id}/tests/{test_id}/` | staff | Price, availability, or remove. |
| POST, PATCH | `/tests/`, `/tests/{id}/` | staff | Catalogue writes. |
| POST | `/bookings/` | JWT | `centre_id`, `test_id`, `appointment_at`. Amount is server-side. |
| GET | `/bookings/` | JWT | Own rows. Staff see all. `?status=`. |
| GET | `/bookings/{id}/` | JWT | Own row, or 404. |
| POST | `/bookings/{id}/cancel/` | JWT | Optional `reason`. |
| POST | `/payments/` | JWT | Header `Idempotency-Key`. Optional `simulate_outcome`. |
| GET | `/payments/{id}/` | JWT | Own payment, or 404. |
| GET | `/bookings/{id}/payments/` | JWT | Attempts for an owned booking. |
| POST | `/payments/webhook/` | HMAC | No JWT. Signature and timestamp. |
| GET | `/health/` | public | `db` and `cache`. 503 if either fails. |

Throttles: signup and login `5/minute`, authenticated `100/minute`, anonymous `30/minute`. The webhook and health check are exempt. A throttle response is `429` with code `THROTTLED`.

### Signup

```bash
curl -s -X POST http://localhost:8000/auth/signup/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"ada@eve.test","password":"Str0ng!Passw0rd","full_name":"Ada Lovelace","phone":"9876543210"}'
```

```json
{
  "user": {
    "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "email": "ada@eve.test",
    "full_name": "Ada Lovelace",
    "phone": "9876543210",
    "date_joined": "2026-09-26T12:00:00Z"
  },
  "access": "<jwt>",
  "refresh": "<jwt>"
}
```

### Login

```bash
curl -s -X POST http://localhost:8000/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@eve.test","password":"Patient#Host2026"}'
```

Unknown emails and wrong passwords both return `401 INVALID_CREDENTIALS` and the message `Invalid email or password.`

### List centres

```bash
curl -s 'http://localhost:8000/centres/?city=Bengaluru&test_code=CBC'
```

### Create a booking

Use ids from the centre detail. The appointment must be in the future, within 90 days, and between 07:00 and 20:00 IST inclusive. A client-sent `amount` is ignored.

```bash
curl -s -X POST http://localhost:8000/bookings/ \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"centre_id":"<centre-uuid>","test_id":"<test-uuid>","appointment_at":"2026-10-01T10:00:00+05:30"}'
```

`201` with `status: "PENDING"` and `amount` equal to that centre's price.

### Pay

```bash
curl -s -X POST http://localhost:8000/payments/ \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: pay-ada-001' \
  -d '{"booking_id":"<booking-uuid>","simulate_outcome":"SUCCESS"}'
```

`201` even when the simulated outcome is `FAILED`. The same key again returns `200` and the original payment. The same key with a different booking returns `422 IDEMPOTENCY_KEY_REUSED`. Omit `simulate_outcome` to use `PAYMENT_SUCCESS_RATE` (default `0.8`).

`simulate_outcome: "PENDING"` returns `201` with the payment `INITIATED` and the booking still `PENDING`. Nothing is confirmed or failed until `POST /payments/webhook/` arrives with a matching `provider_reference`. Use the `provider_reference` from that response when you sign the webhook.

### Webhook

```bash
python scripts/simulate_webhook.py --provider-reference sim_pay_demo --times 3
```

`make webhook` runs that. Example output when the same `event_id` is delivered three times:

```text
POST 1 -> 200 {"status": "accepted"}
POST 2 -> 200 {"status": "duplicate", "event_id": "evt_demo"}
POST 3 -> 200 {"status": "duplicate", "event_id": "evt_demo"}
```

The signature is `sha256=` plus HMAC-SHA256 of the raw body, using `WEBHOOK_SECRET`. `X-Webhook-Timestamp` is unix seconds or an ISO-8601 time. Times older than five minutes are rejected.

### Cancel

```bash
curl -s -X POST http://localhost:8000/bookings/<booking-uuid>/cancel/ \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"reason":"Schedule changed"}'
```

## Idempotency & consistency

Five mechanisms sit on top of each other:

1. **`Idempotency-Key`.** Unique per user. A replay returns the stored payment and does not charge again. A reused key for a different booking is `422`.
2. **`WebhookEvent.event_id`.** `get_or_create` inside a transaction. A concurrent insert hits the unique constraint, is caught as `IntegrityError`, and answered as `{"status":"duplicate"}` with no second task.
3. **`select_for_update`.** Payment creation locks the booking. The webhook task locks the event, then the booking, then the payment. `apply_payment_result` locks booking then payment in the same order.
4. **Partial unique indexes.** Two active duplicate bookings cannot both commit. Two `SUCCESS` payments for one booking cannot both commit.
5. **`apply_payment_result` is order-safe.** Already in the target status: no-op. `SUCCESS` then a late `payment.failed`: ignored, success stays. Booking already `CANCELLED` when `payment.succeeded` arrives: payment becomes `SUCCESS`, booking stays `CANCELLED`, and the log sets `refund_required=true`.

A webhook looks up an existing payment by `provider_reference`. An unknown reference or an amount/currency mismatch marks the event `FAILED` and does not change the booking. Those are domain errors and are not retried. `OperationalError` is retried with backoff, up to five times, and `attempts` / `last_error` are stored. Tests run Celery eagerly (`CELERY_TASK_ALWAYS_EAGER`).

## Edge cases handled

| Situation | Result |
|---|---|
| Duplicate email, any case | 409 `EMAIL_ALREADY_REGISTERED` |
| Unknown email or wrong password | 401 `INVALID_CREDENTIALS` (same message) |
| Missing or expired access token | 401 `NOT_AUTHENTICATED` / `AUTHENTICATION_FAILED` |
| Non-staff catalogue write | 403 `PERMISSION_DENIED` |
| Another user's booking or payment | 404 `NOT_FOUND` |
| Malformed UUID in the path | 404 `NOT_FOUND` |
| Past, beyond 90 days, or outside 07:00–20:00 IST | 400 `VALIDATION_ERROR` |
| Inactive centre or test, not offered, or unavailable | 400 with `CENTRE_INACTIVE`, `TEST_INACTIVE`, `TEST_NOT_OFFERED_AT_CENTRE`, or `TEST_UNAVAILABLE` |
| Second active booking for the same slot | 409 `DUPLICATE_BOOKING` |
| Illegal status change | 409 `INVALID_STATE_TRANSITION` |
| Cancel a confirmed booking within 2 hours | 409 `CANCELLATION_WINDOW_CLOSED` |
| Missing `Idempotency-Key` | 400 `IDEMPOTENCY_KEY_REQUIRED` |
| Same key, different booking | 422 `IDEMPOTENCY_KEY_REUSED` |
| Pay a confirmed booking | 409 `BOOKING_ALREADY_PAID` |
| Pay a failed or cancelled booking | 409 `BOOKING_NOT_PAYABLE` |
| Appointment no longer in the future | 409 `BOOKING_EXPIRED` |
| Simulated payment failure | 201 with payment and booking `FAILED` |
| `simulate_outcome` `PENDING` | 201, payment `INITIATED`, booking stays `PENDING` until the webhook |
| Bad, missing, or stale webhook signature | 401 `INVALID_WEBHOOK_SIGNATURE` |
| Malformed webhook body | 400 `VALIDATION_ERROR` or `PARSE_ERROR` |
| Unknown `event_type` | 200, event stored as `IGNORED` |
| Duplicate `event_id`, even with a different body | 200 `duplicate`, original payload kept |
| Unknown `provider_reference` or amount mismatch | 200 accepted, event `FAILED`, booking unchanged |
| Late failure after success | ignored, booking stays `CONFIRMED` |
| Success webhook after the user cancelled | booking stays `CANCELLED`, refund logged |
| Too many login attempts | 429 `THROTTLED` |
| Unexpected exception | 500 `INTERNAL_ERROR`, no traceback in the body |

## Testing

```bash
export DJANGO_SETTINGS_MODULE=config.settings.test
export SECRET_KEY=test-secret-key-not-for-production
export DATABASE_URL=postgres://eve:eve@127.0.0.1:5432/eve
export REDIS_URL=redis://127.0.0.1:6379/1
pytest --cov --cov-fail-under=90
```

`make test` runs pytest. `make coverage` enforces the 90% gate. Tests use PostgreSQL and Redis, factories for every model, and `freezegun` for token expiry and the cancellation window. Covered areas: auth, catalogue filters and cache invalidation, booking rules, every allowed and disallowed state transition, payment idempotency, the partial unique success index, signed webhooks including three duplicate deliveries, a threaded duplicate-event race, health, the error envelope, and login throttling. The latest local run covered about 96% of `apps` and `config`. CI fails the job under 90%, and also runs `ruff check`, `ruff format --check`, and `makemigrations --check`.

## Assumptions

- One test per booking. A cart of several tests would be a new model.
- The price is snapshotted. The client cannot send an amount.
- `FAILED` is terminal. The user books again.
- Centres are open 07:00–20:00 IST, every day, with no slot capacity limit.
- Staff manage the catalogue. Everyone else can read active centres.
- Another user's booking or payment is `404`, so ids cannot be probed.
- Payment amount and currency are taken from the server-side payment row.
- A webhook finds its payment by `provider_reference`. It cannot create one.
- The only currency is INR.
- Cancelling a confirmed booking logs that a refund would be triggered. No refund is sent.
- There is no `/api/v1` prefix yet.

## What I'd improve with more time

- Slot capacity and an availability calendar, so two patients cannot take the same chair.
- A real gateway (Razorpay) behind `PaymentSimulator`, with the webhook still calling `apply_payment_result`.
- A refund flow for confirmed cancellations and for a success that arrives after cancel.
- An outbox so domain events are published in the same transaction as the booking change.
- API versioning (`/api/v1`) once an external client ships.
- Email and SMS when a booking is confirmed or cancelled.
- An audit-log table for staff edits and status changes.
- Sentry plus Prometheus metrics.
- A cache per endpoint, with a clear invalidation story beyond the centre list.
- Load tests around the payment lock and the webhook unique constraint.

## Project structure

```text
eve-healthcare-backend/
├── config/                  # settings, urls, celery, wsgi
│   └── settings/
│       ├── base.py
│       ├── dev.py
│       └── test.py
├── apps/
│   ├── accounts/            # custom User, signup, login, me
│   ├── catalog/             # centres, tests, per-centre prices, seed
│   ├── bookings/            # booking model, state machine, APIs
│   ├── payments/            # attempts, simulator, signed webhook, Celery task
│   └── core/                # errors, pagination, logging, health
├── tests/                   # mirrors the apps, plus factories and conftest
├── scripts/simulate_webhook.py
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── .env.example
├── requirements.txt
└── requirements-dev.txt
```
