# Manual end-to-end test workflow (real data)

Use this when you (or a reviewer) want to prove the API works by hand in Swagger or curl.

**Database:** PostgreSQL (as preferred in the assignment).  
**Recommended run mode:** Docker Compose — Postgres and Redis run **inside containers**. You do **not** install or seed a host/local PostgreSQL.

```bash
cp .env.example .env          # if you do not already have .env
docker compose up --build -d
# wait ~30s, then:
curl http://localhost:8000/health/
docker compose exec web python manage.py seed_data   # safe to re-run
```

Open Swagger: http://localhost:8000/docs/

Seeded accounts (created by `seed_data`, not fake Swagger placeholders):

| Role | Email | Password |
|---|---|---|
| Patient | `demo@eve.test` | `Patient#Host2026` |
| Admin (staff) | `admin@eve.test` | `Clinic#Host2026` |

> **Rule:** Never copy UUIDs from Swagger “Example Value / Schema” panels (`3fa85f64-…`). Only copy values from the **Server response** after you click **Execute**.

---

## Answers reviewers often ask

### Are endpoints different for admin and patients?

**Same URL paths for everyone.** Access differs by role on some routes:

| Area | Patient (JWT, not staff) | Admin / staff (JWT, `is_staff`) |
|---|---|---|
| Auth login / signup / me | Yes | Yes |
| `GET /centres/`, `GET /tests/` | Yes (public or JWT) | Yes |
| `POST/PATCH/DELETE /centres/…`, add/edit centre tests | **403** | Yes |
| `POST /bookings/`, pay, cancel **own** bookings | Yes | Yes (staff can also list all bookings) |
| Another user’s booking / payment | **404** (not 403) | Staff can see bookings broadly; payments stay owner-scoped |

So: not separate “admin API” vs “patient API” hosts — one API, permission checks on write/catalog admin actions.

### Are optional bonuses from the PDF implemented?

**Yes.** Assignment optional items:

| Bonus | Status |
|---|---|
| Redis caching | Yes (centre list cache) |
| Celery / background jobs | Yes (webhook processing) |
| Docker & docker-compose | Yes |
| Swagger / OpenAPI | Yes (`/docs/`, `/schema/`) |
| Unit / integration tests | Yes (`make test`, coverage ≥ 90%) |
| Structured logging | Yes (JSON logs + `request_id`) |
| Pagination | Yes |
| Rate limiting | Yes (auth 5/min, etc.) |
| Retry handling for webhooks | Yes (Celery retries on `OperationalError`) |

---

## Successful patient workflow (must pass)

Do steps in order. After each step, the **Expect** block is what “success” looks like.

### Step 0 — Health

- **Method / path:** `GET /health/`
- **Auth:** none
- **Body:** none  
- **Expect:** `200`

```json
{ "status": "ok", "db": "ok", "cache": "ok" }
```

---

### Step 1 — Login as patient

- **Method / path:** `POST /auth/login/`
- **Auth:** none  
- **Body:**

```json
{
  "email": "demo@eve.test",
  "password": "Patient#Host2026"
}
```

- **Expect:** `200` with `access` and `refresh`  
- **Save:** `access` → click **Authorize** in Swagger → `Bearer <access>` (or paste token only, depending on UI)

---

### Step 2 — Confirm identity

- **Method / path:** `GET /auth/me/`
- **Auth:** Bearer patient token  
- **Expect:** `200`, `"email": "demo@eve.test"`, **no** `password` field

---

### Step 3 — List centres (real catalogue)

- **Method / path:** `GET /centres/?city=Guwahati`
- **Auth:** none (or Bearer)  
- **Expect:** `200`, paginated `{ "count", "next", "previous", "results" }`, `count` ≥ 1  
- **Save:** `results[0].id` → `CENTRE_ID`

---

### Step 4 — Centre detail (real test + price)

- **Method / path:** `GET /centres/{CENTRE_ID}/`
- **Expect:** `200` with `tests` array; each item has `id`, `code`, `name`, `price`  
- Prefer a row with `"code": "CBC"`  
- **Save:** that test’s `id` → `TEST_ID`, and `price` → `EXPECTED_AMOUNT`

---

### Step 5 — Create booking

- **Method / path:** `POST /bookings/`
- **Auth:** Bearer patient token  
- **Body** (use a **future** slot, 07:00–20:00 IST, within 90 days — change the date if needed):

```json
{
  "centre_id": "<CENTRE_ID from step 3>",
  "test_id": "<TEST_ID from step 4>",
  "appointment_at": "2026-10-10T10:00:00+05:30"
}
```

- **Expect:** `201`

```json
{
  "id": "<real-uuid>",
  "status": "PENDING",
  "amount": "<same as EXPECTED_AMOUNT>",
  "centre_id": "...",
  "test_id": "...",
  "appointment_at": "..."
}
```

- **Save:** response `id` → `BOOKING_ID`  
  (This is the only `booking_id` valid for payment.)

---

### Step 6 — Pay (SUCCESS)

- **Method / path:** `POST /payments/`
- **Auth:** Bearer patient token  
- **Header (required):** `Idempotency-Key: pay-demo-001`  
  (any unique string you invent; Swagger shows this field under Parameters)  
- **Body:**

```json
{
  "booking_id": "<BOOKING_ID from step 5>",
  "simulate_outcome": "SUCCESS"
}
```

- **Expect:** `201`

```json
{
  "id": "<payment-uuid>",
  "booking_id": "<BOOKING_ID>",
  "status": "SUCCESS",
  "amount": "<same as booking amount>",
  "booking_status": "CONFIRMED",
  "provider_reference": "..."
}
```

- **Save:** payment `id` → `PAYMENT_ID`

---

### Step 7 — Verify booking confirmed

- **Method / path:** `GET /bookings/{BOOKING_ID}/`
- **Auth:** Bearer patient token  
- **Expect:** `200`, `"status": "CONFIRMED"`

---

### Step 8 — Idempotent replay (same key)

- Repeat **Step 6** with the **same** `Idempotency-Key: pay-demo-001` and same body.  
- **Expect:** `200` (not a second charge), **same** payment `id` as step 6.

---

### Step 9 — Cancel (optional but recommended)

- **Method / path:** `POST /bookings/{BOOKING_ID}/cancel/`
- **Auth:** Bearer patient token  
- **Body:** `{ "reason": "Schedule changed" }`  
- **Expect:** `200`, `"status": "CANCELLED"`, `cancelled_at` set

---

## Checklist — claim “successful testing”

| # | Check | Pass? |
|---|---|---|
| 1 | Health `db` + `cache` = `ok` | |
| 2 | Login returns JWT | |
| 3 | Centres + nested tests/prices from seed | |
| 4 | Booking `201` / `PENDING` / server amount | |
| 5 | Payment `201` / `SUCCESS` / booking `CONFIRMED` | |
| 6 | Same Idempotency-Key → `200` same payment | |
| 7 | Errors are JSON `{ "error": { "code", "message", "details" } }` | |

If all of the above pass, the core assignment (auth, centres/tests, bookings, simulated payment, edge cases around idempotency) is verified on a running stack.

---

## Admin-only smoke (optional, shows staff vs patient)

1. `POST /auth/login/` with `admin@eve.test` / `Clinic#Host2026` → Authorize with that token.  
2. `POST /centres/` with a new name/city → **Expect `201`**.  
3. Switch back to patient token → same `POST /centres/` → **Expect `403 PERMISSION_DENIED`**.

---

## Async payment + webhook (optional bonus path)

1. Create another booking (new `appointment_at` so it does not collide).  
2. `POST /payments/` with `simulate_outcome: "PENDING"` and a **new** Idempotency-Key.  
   - Expect payment `INITIATED`, booking still `PENDING`. Copy `provider_reference`.  
3. From the project root:

```bash
python scripts/simulate_webhook.py --provider-reference <provider_reference>
```

4. `GET /bookings/{id}/` → expect `CONFIRMED`.  
5. Run the webhook script again with the same event → expect `duplicate` (idempotent webhook).

---

## Automated proof (for submission)

```bash
make test     # pytest + coverage gate
make smoke    # full live HTTP matrix against Compose
```

Both green = strong evidence for the company beyond manual Swagger clicks.

---

## Common mistakes

| Mistake | Result | Fix |
|---|---|---|
| Using example UUID `3fa85f64-…` | `404 NOT_FOUND` | Use `id` from a real `201` booking response |
| Missing `Idempotency-Key` | `400 IDEMPOTENCY_KEY_REQUIRED` | Fill the header in Swagger Parameters |
| Appointment outside 07:00–20:00 IST or in the past | `400 VALIDATION_ERROR` | Use a future weekday morning IST time |
| Paying another user’s booking | `404` | Login as the same user who created it |
| Hitting `http://localhost:8000/` root | `404 NOT_FOUND` | Use `/docs/` or `/health/` |
