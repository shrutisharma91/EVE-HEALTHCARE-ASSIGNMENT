# API test plan

Black-box checks against a running stack (`web`, Postgres, Redis, Celery). The runner is `scripts/api_smoke_test.py`. The same cases are in `postman/EVE_Healthcare.postman_collection.json`.

Conventions:

- `A` / `B` / `ADM` are tokens for user A, user B, and the seeded admin. `—` means no `Authorization` header.
- Each run creates `user_a_<timestamp>@test.dev` and `user_b_<timestamp>@test.dev` with password `Str0ng!Pass#1`.
- `{slot_n}` is a unique future time inside 07:00–20:00 IST. The runner uses tomorrow 10:00 IST, tomorrow 11:00 IST, then later 20-minute steps.
- `{cid}` is the seeded Guwahati centre. `{tid}` is CBC at that centre. A test the centre does not offer (XRAY_CHEST) is used for B6.
- Negative cases must return the JSON envelope `{"error": {"code": str, "message": str, "details": ...}}`. No HTML body and no HTTP 500.
- Webhook calls send `X-Webhook-Signature: sha256=HMAC_SHA256(WEBHOOK_SECRET, raw_body)` and `X-Webhook-Timestamp` as unix seconds.
- After an accepted webhook the runner polls `GET /payments/{id}/` and `GET /bookings/{id}/` every 250 ms for up to 10 s. `WebhookEvent` rows are read with `docker compose exec -T web python manage.py shell`, not via a public route.
- B24 runs after P6. Cancelling `{b1}` first would make P6 return `BOOKING_NOT_PAYABLE` instead of `BOOKING_ALREADY_PAID`.
- The runner flushes Redis before X3 so the 5/minute auth limit starts at zero. `make smoke` also passes `--flush-throttle` at the start. Functional cases that hit `429 THROTTLED` are retried once the window passes. X3 is not retried.

## H — Health and docs

| ID | Label | Request | Auth | Expected |
|---|---|---|---|---|
| H1 | Health check | `GET /health/` | — | 200, `status=ok`, `db=ok`, `cache=ok` |
| H2 | Swagger UI loads | `GET /docs/` | — | 200, HTML |
| H3 | OpenAPI schema | `GET /schema/` | — | 200, body contains `/payments/webhook/` |
| H4 | Request ID header | `GET /health/` with `X-Request-ID: smoke-123` | — | response header `X-Request-ID: smoke-123` |
| H5 | Unknown route | `GET /does-not-exist/` | — | 404, JSON envelope, code `NOT_FOUND` |
| H6 | Wrong method | `PUT /health/` | — | 405, envelope, code `METHOD_NOT_ALLOWED` |

## AU — Authentication

| ID | Label | Request | Auth | Expected |
|---|---|---|---|---|
| AU1 | Signup success | `POST /auth/signup/` `{email, password, full_name:"User A", phone:"9876543210"}` | — | 201, user object (no `password` field), `access` + `refresh` |
| AU2 | Signup user B | same with B's email and phone `9123456780` | — | 201 |
| AU3 | Duplicate email, different case | A's email in UPPERCASE | — | 409 `EMAIL_ALREADY_REGISTERED` |
| AU4 | Weak password | `password:"123"` | — | 400 `VALIDATION_ERROR`, `details.password` present |
| AU5 | Missing email | no `email` | — | 400 `VALIDATION_ERROR`, `details.email` |
| AU6 | Invalid email format | `email:"not-an-email"` | — | 400 `VALIDATION_ERROR`, `details.email` |
| AU7 | Invalid phone | `phone:"12345"` | — | 400 `VALIDATION_ERROR`, `details.phone` |
| AU8 | Empty body | `{}` | — | 400 `VALIDATION_ERROR` |
| AU9 | Malformed JSON | raw body `{"email":` | — | 400 `PARSE_ERROR`, not 500 |
| AU10 | Login success | `POST /auth/login/` A creds | — | 200, `access`, `refresh` |
| AU11 | Wrong password | A email + wrong password | — | 401 `INVALID_CREDENTIALS` |
| AU12 | Unknown email | random email | — | 401 `INVALID_CREDENTIALS`, same message as AU11 |
| AU13 | Me with token | `GET /auth/me/` | A | 200, email = A, no password field |
| AU14 | Me without token | `GET /auth/me/` | — | 401 `NOT_AUTHENTICATED` |
| AU15 | Me with garbage token | `Authorization: Bearer abc.def.ghi` | — | 401 `AUTHENTICATION_FAILED` |
| AU16 | Refresh token | `POST /auth/token/refresh/` `{refresh}` from AU10 | — | 200, new `access` and new `refresh` |
| AU17 | Reuse rotated refresh | old refresh from AU16 again | — | 401 `AUTHENTICATION_FAILED` |
| AU18 | Expired access token | — | — | SKIP (`tests/accounts/test_auth.py::test_expired_access_token_is_rejected`) |

## C — Catalog

| ID | Label | Request | Auth | Expected |
|---|---|---|---|---|
| C1 | List centres | `GET /centres/` | — | 200, paginated (`count`, `next`, `previous`, `results`), count ≥ 5 |
| C2 | Filter by city | `?city=Guwahati` | — | 200, every result city = Guwahati |
| C3 | Filter by test | `?test_code=CBC` | — | 200, every result offers CBC |
| C4 | Search by name | `?search=Guwahati` | — | 200, every result name contains Guwahati |
| C5 | Page size | `?page_size=2` | — | 200, 2 results, `next` not null |
| C6 | Oversized page size | `?page_size=10000` | — | 200, ≤ 100 results, no 500 |
| C7 | Page out of range | `?page=9999` | — | 404, envelope, code `NOT_FOUND` |
| C8 | Centre detail | `GET /centres/{cid}/` | — | 200, nested tests with `price` |
| C9 | Centre not found | nonexistent id | — | 404, envelope, code `NOT_FOUND` |
| C10 | Centre tests | `GET /centres/{cid}/tests/` | — | 200, tests and prices |
| C11 | Test catalogue | `GET /tests/?search=thyroid` | — | 200, results include Thyroid Profile |
| C12 | Anonymous create | `POST /centres/` | — | 401 `NOT_AUTHENTICATED` |
| C13 | Non-admin create | `POST /centres/` | A | 403 `PERMISSION_DENIED` |
| C14 | Admin create centre | `{name:"Smoke Lab <ts>", address, city:"Guwahati", pincode:"781001", phone}` | ADM | 201 |
| C15 | Duplicate name + city | same as C14 | ADM | 409 `CENTRE_ALREADY_EXISTS` |
| C16 | Invalid pincode | `pincode:"12"` | ADM | 400 `VALIDATION_ERROR`, `details.pincode` |
| C17 | Add test to centre | `POST /centres/{new}/tests/` `{test_id, price:"450.00"}` | ADM | 201 |
| C18 | Zero/negative price | `price:"0"` and `price:"-10"` | ADM | 400 `VALIDATION_ERROR`, `details.price` each |
| C19 | Same test twice | repeat C17 | ADM | 409 `TEST_ALREADY_OFFERED` |
| C20 | Update price, cache invalidated | PATCH price to `"500.00"`, then `GET /centres/{new}/` | ADM | GET shows 500.00 immediately |
| C21 | Soft delete | `DELETE /centres/{new}/`, then public list + detail | ADM | 204; absent from the public list; unauthenticated detail 404 `NOT_FOUND` |

## B — Bookings

| ID | Label | Request | Auth | Expected |
|---|---|---|---|---|
| B1 | Create booking | `POST /bookings/` `{centre_id:{cid}, test_id:{tid}, appointment_at:{slot_1}}` | A | 201, `status=PENDING`, `amount` = centre price for that test |
| B2 | Client amount ignored | B1 body + `amount:"1.00"`, `{slot_2}` | A | 201, amount = real price |
| B3 | Past appointment | yesterday 10:00 IST | A | 400 `VALIDATION_ERROR`, `details.appointment_at` |
| B4 | Beyond 90 days | today + 120 days at 10:00 IST | A | 400 `VALIDATION_ERROR`, `details.appointment_at` |
| B5 | Outside operating hours | tomorrow 22:00 IST | A | 400 `VALIDATION_ERROR`, `details.appointment_at` |
| B6 | Test not offered at centre | XRAY_CHEST at `{cid}` | A | 400 `TEST_NOT_OFFERED_AT_CENTRE` |
| B7 | Test unavailable at centre | admin sets `is_available=false` on URINE, then book | A | 400 `TEST_UNAVAILABLE`, then availability is restored |
| B8 | Inactive centre | soft-deleted centre from C21 | A | 400 `CENTRE_INACTIVE` |
| B9 | Nonexistent centre | random id | A | 404 `NOT_FOUND` |
| B10 | Missing fields | `{}` | A | 400 `VALIDATION_ERROR`, details for `centre_id`, `test_id`, `appointment_at` |
| B11 | Bad datetime | `appointment_at:"tomorrow"` | A | 400 `VALIDATION_ERROR`, `details.appointment_at` |
| B12 | Duplicate active booking | repeat B1 exactly | A | 409 `DUPLICATE_BOOKING` |
| B13 | No token | B1 body | — | 401 `NOT_AUTHENTICATED` |
| B14 | List own only | `GET /bookings/` as B | B | 200, count 0 |
| B15 | Filter by status | `GET /bookings/?status=PENDING` | A | 200, every result PENDING |
| B16 | Get own booking | `GET /bookings/{b1}/` | A | 200 |
| B17 | Get other's booking | `GET /bookings/{b1}/` | B | 404 `NOT_FOUND` |
| B18 | Malformed UUID | `GET /bookings/not-a-uuid/` | A | 404 `NOT_FOUND`, not 500 |
| B19 | Cancel pending | `POST /bookings/{b2}/cancel/` `{reason:"test"}` | A | 200, `CANCELLED`, `cancelled_at` set |
| B20 | Cancel again | repeat B19 | A | 409 `INVALID_STATE_TRANSITION` |
| B21 | Cancel other's booking | `POST /bookings/{b1}/cancel/` | B | 404 `NOT_FOUND` |
| B22 | Rebook cancelled slot | same centre/test/`{slot_2}` as B2 | A | 201 |
| B23 | Price snapshot | admin changes the price of `{tid}` at `{cid}`, then `GET /bookings/{b1}/` | A | amount unchanged; price restored afterwards |
| B24 | Cancel confirmed > 2h away | `POST /bookings/{b1}/cancel/` after P6 | A | 200, `CANCELLED` |
| B25 | Cancel confirmed < 2h away | — | — | SKIP (`tests/bookings/test_bookings.py::test_cancel_follows_the_state_machine`) |

## P — Simulated payments

Each case sends a fresh `Idempotency-Key` (UUID) unless the row says otherwise.

| ID | Label | Request | Auth | Expected |
|---|---|---|---|---|
| P1 | Success | `{booking_id:{b1}, simulate_outcome:"SUCCESS"}` | A | 201, payment `SUCCESS`, amount = booking amount; booking `CONFIRMED` |
| P2 | Failure | new booking `{b3}`, `simulate_outcome:"FAILED"` | A | 201, payment `FAILED`, `failure_reason` set; booking `FAILED` |
| P3 | Missing Idempotency-Key | no header | A | 400 `IDEMPOTENCY_KEY_REQUIRED` |
| P4 | Idempotent replay | repeat P1 with the same key | A | 200, same payment id; `GET /bookings/{b1}/payments/` count is 1 |
| P5 | Key reused, different booking | P1's key with a new booking `{b4}` | A | 422 `IDEMPOTENCY_KEY_REUSED` |
| P6 | Pay confirmed booking | `{b1}`, new key | A | 409 `BOOKING_ALREADY_PAID` |
| P7 | Pay failed booking | `{b3}`, new key | A | 409 `BOOKING_NOT_PAYABLE` |
| P8 | Pay cancelled booking | `{b2}`, new key | A | 409 `BOOKING_NOT_PAYABLE` |
| P9 | Pay other's booking | `{b1}` | B | 404 `NOT_FOUND` |
| P10 | Nonexistent booking | random uuid | A | 404 `NOT_FOUND` |
| P11 | Malformed booking_id | `"abc"` | A | 400 `VALIDATION_ERROR`, `details.booking_id` |
| P12 | Invalid outcome | `simulate_outcome:"MAYBE"` | A | 400 `VALIDATION_ERROR`, `details.simulate_outcome` |
| P13 | Client amount ignored | new booking + `amount:"1.00"` | A | 201, amount = booking amount |
| P14 | No token | — | — | 401 `NOT_AUTHENTICATED` |
| P15 | Get own payment / other's | `GET /payments/{p1}/` | A / B | 200 / 404 `NOT_FOUND` |
| P16 | Booking payment history | `GET /bookings/{b3}/payments/` | A | 200, count 1, status `FAILED` |
| P17 | Pending outcome | new booking `{b5}`, `simulate_outcome:"PENDING"` | A | 201, payment `INITIATED`, booking stays `PENDING` |
| P18 | Race: parallel payments | 5 concurrent requests on new booking `{b6}`, different keys, all `SUCCESS` | A | exactly one 201 `SUCCESS`; the rest 409; booking has exactly one `SUCCESS` payment |
| P19 | Pay expired booking | — | — | SKIP (`tests/payments/test_payments.py::test_expired_booking_cannot_be_paid`) |

## W — Webhook

| ID | Label | Request | Expected |
|---|---|---|---|
| W1 | Success settles payment | `payment.succeeded` for pending payment `{p17}` | 200 `accepted`; after polling, payment `SUCCESS`, booking `CONFIRMED`; event `PROCESSED` |
| W2 | Duplicate ×3 | resend the W1 body 3 times | 200 `duplicate` each; 1 `WebhookEvent` row; booking still `CONFIRMED`; still 1 `SUCCESS` payment |
| W3 | Same event_id, different payload | W1's `event_id` with `event_type:"payment.failed"` | 200 `duplicate`; payment stays `SUCCESS`, booking stays `CONFIRMED`; still 1 row |
| W4 | Failure settles payment | `payment.failed` for a new pending payment | payment `FAILED`, booking `FAILED`; event `PROCESSED` |
| W5 | Late failure after success | `payment.failed` (new event_id) for `{p17}` | 200; after the event is `PROCESSED`, payment stays `SUCCESS`, booking stays `CONFIRMED` |
| W6 | Success after cancel | new pending payment, cancel its booking, then `payment.succeeded` | payment `SUCCESS`, booking stays `CANCELLED`; worker log contains `refund_required` true for that payment |
| W7 | Amount mismatch | `payment.succeeded` with the wrong `amount` | 200; booking stays `PENDING`, payment stays `INITIATED`; event `FAILED` |
| W8 | Unknown provider_reference | `sim_pay_doesnotexist` | 200; event `FAILED`; a control booking's status and payment count stay the same |
| W9 | Unknown event_type | `payment.refunded_maybe` | 200 `ignored`; event `IGNORED` |
| W10 | Invalid signature | wrong HMAC | 401 `INVALID_WEBHOOK_SIGNATURE`; no event row |
| W11 | Missing signature | no signature header | 401 `INVALID_WEBHOOK_SIGNATURE`; no event row |
| W12 | Stale timestamp | timestamp = now − 10 min, correctly signed | 401 `INVALID_WEBHOOK_SIGNATURE` |
| W13 | Malformed payload | signed body missing `data` | 400 `VALIDATION_ERROR`; no event row |
| W14 | Body tampered after signing | sign, then change the amount | 401 `INVALID_WEBHOOK_SIGNATURE`; no event row |
| W15 | Concurrent duplicates | 10 parallel identical signed events for a new pending payment | all 200; exactly 1 event row `PROCESSED`; booking `CONFIRMED` once |
| W16 | No JWT needed / GET not allowed | `GET /payments/webhook/` | 405 `METHOD_NOT_ALLOWED` |

## X — Cross-cutting

Run last.

| ID | Label | Request | Expected |
|---|---|---|---|
| X1 | Envelope audit | every non-2xx response in the run | JSON with `error.code` and `error.message`; zero HTTP 500s |
| X2 | No secrets in responses | every response body | no `password` field, no password hash, no `WEBHOOK_SECRET` value, no stack trace |
| X3 | Login throttling | 6 wrong-password logins within 60 s from one client, after a throttle flush | first 5 are 401; 6th is 429 `THROTTLED` |
| X4 | Logs are structured | `docker compose logs web` | JSON log lines contain `request_id`; a `webhook_duplicate` event from W2 is present |

## Notes on the original matrix

These are plan corrections. The implementation and the existing pytest suite already agreed, so the expected value was updated here rather than in the code.

| Topic | Resolution |
|---|---|
| C15 duplicate centre | 409 `CENTRE_ALREADY_EXISTS`. The prompt said 400. `CentreAlreadyExists` and the README both use 409. |
| C19 same test twice | 409 `TEST_ALREADY_OFFERED`. The prompt allowed 400 or 409. The service always uses 409. |
| C21 detail after soft delete | Public `GET` is 404. A staff token still receives the inactive centre so it can be restored. The prompt's "detail 404" is the public result. |
| B8 inactive centre | 400 `CENTRE_INACTIVE`. The prompt allowed 400 or 404. |
| B9 unknown centre | 404 `NOT_FOUND`. The prompt allowed 400 or 404. A missing row is a 404; an inactive row is B8. |
| X3 throttle code | `THROTTLED`. The prompt allowed `RATE_LIMITED` or the project's code. README and `test_login_is_throttled` use `THROTTLED`. |
| AU17 reused refresh | 401 `AUTHENTICATION_FAILED`. SimpleJWT blacklist failures use the standard auth envelope. |
| AU9 malformed JSON | 400 `PARSE_ERROR`. |
| H6 wrong method | 405 `METHOD_NOT_ALLOWED`. |
| W9 unknown event | HTTP body `status` is `ignored`, and the row is `IGNORED`. |
| X2 secret scan | The words in `Invalid email or password.` are not a leaked secret. Validation envelopes may include `details.password` as a field name (AU4). The scan rejects a top-level `password` field, a hash, the webhook secret, and a traceback. |
| X4 log window | The runner reads the web log since the run started. `--tail 50` can drop `webhook_duplicate` once later webhook and access lines are included. |
| B24 order | Runs after P6 so `{b1}` is still `CONFIRMED` when P6 executes. |
| X2 AU4/AU8 false positive | Fixed in the runner: `error.details.password` is a validation key, not a credential leak. |
