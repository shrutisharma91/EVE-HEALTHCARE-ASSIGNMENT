# API test report

- **Timestamp:** 2026-09-29T12:10:45Z
- **Git commit:** `cf053ae3c93ce96745089ec82e518394775c1e13`
- **Base URL:** http://localhost:8000

## Summary

| Total | Passed | Failed | Skipped |
| --- | --- | --- | --- |
| 109 | 106 | 0 | 3 |

## Cases

| ID | Result | Label | Detail |
| --- | --- | --- | --- |
| H1 | PASS | Health check |  |
| H2 | PASS | Swagger UI loads |  |
| H3 | PASS | OpenAPI schema |  |
| H4 | PASS | Request ID header |  |
| H5 | PASS | Unknown route |  |
| H6 | PASS | Wrong method |  |
| AU1 | PASS | Signup success |  |
| AU2 | PASS | Signup user B |  |
| AU3 | PASS | Duplicate email, different case |  |
| AU4 | PASS | Weak password |  |
| AU5 | PASS | Missing email |  |
| AU6 | PASS | Invalid email format |  |
| AU7 | PASS | Invalid phone |  |
| AU8 | PASS | Empty body |  |
| AU9 | PASS | Malformed JSON |  |
| AU10 | PASS | Login success |  |
| AU11 | PASS | Wrong password |  |
| AU12 | PASS | Unknown email |  |
| AU13 | PASS | Me with token |  |
| AU14 | PASS | Me without token |  |
| AU15 | PASS | Me with garbage token |  |
| AU16 | PASS | Refresh token |  |
| AU17 | PASS | Reuse rotated refresh |  |
| AU18 | SKIP | Expired access token | covered by pytest: test_expired_access_token_is_rejected |
| C1 | PASS | List centres |  |
| C2 | PASS | Filter by city |  |
| C3 | PASS | Filter by test |  |
| C4 | PASS | Search by name |  |
| C5 | PASS | Page size |  |
| C6 | PASS | Oversized page size |  |
| C7 | PASS | Page out of range |  |
| C8 | PASS | Centre detail |  |
| C9 | PASS | Centre not found |  |
| C10 | PASS | Centre tests |  |
| C11 | PASS | Test catalogue |  |
| C12 | PASS | Anonymous create |  |
| C13 | PASS | Non-admin create |  |
| C14 | PASS | Admin create centre |  |
| C15 | PASS | Duplicate name + city |  |
| C16 | PASS | Invalid pincode |  |
| C17 | PASS | Add test to centre |  |
| C18 | PASS | Zero/negative price |  |
| C19 | PASS | Same test twice |  |
| C20 | PASS | Update price, cache invalidated |  |
| C21 | PASS | Soft delete |  |
| B1 | PASS | Create booking |  |
| B2 | PASS | Client amount ignored |  |
| B3 | PASS | Past appointment |  |
| B4 | PASS | Beyond 90 days |  |
| B5 | PASS | Outside operating hours |  |
| B6 | PASS | Test not offered at centre |  |
| B7 | PASS | Test unavailable at centre |  |
| B8 | PASS | Inactive centre |  |
| B9 | PASS | Nonexistent centre |  |
| B10 | PASS | Missing fields |  |
| B11 | PASS | Bad datetime |  |
| B12 | PASS | Duplicate active booking |  |
| B13 | PASS | No token |  |
| B14 | PASS | List own only |  |
| B15 | PASS | Filter by status |  |
| B16 | PASS | Get own booking |  |
| B17 | PASS | Get other's booking |  |
| B18 | PASS | Malformed UUID |  |
| B19 | PASS | Cancel pending |  |
| B20 | PASS | Cancel again |  |
| B21 | PASS | Cancel other's booking |  |
| B22 | PASS | Rebook cancelled slot |  |
| B23 | PASS | Price snapshot |  |
| B25 | SKIP | Cancel confirmed < 2h away | covered by pytest: test_cancel_follows_the_state_machine |
| P1 | PASS | Success |  |
| P2 | PASS | Failure |  |
| P3 | PASS | Missing Idempotency-Key |  |
| P4 | PASS | Idempotent replay |  |
| P5 | PASS | Key reused, different booking |  |
| P6 | PASS | Pay confirmed booking |  |
| B24 | PASS | Cancel confirmed > 2h away |  |
| P7 | PASS | Pay failed booking |  |
| P8 | PASS | Pay cancelled booking |  |
| P9 | PASS | Pay other's booking |  |
| P10 | PASS | Nonexistent booking |  |
| P11 | PASS | Malformed booking_id |  |
| P12 | PASS | Invalid outcome |  |
| P13 | PASS | Client amount ignored |  |
| P14 | PASS | No token |  |
| P15 | PASS | Get own payment / other's |  |
| P16 | PASS | Booking payment history |  |
| P17 | PASS | Pending outcome |  |
| P18 | PASS | Race: parallel payments |  |
| P19 | SKIP | Pay expired booking | covered by pytest: test_expired_booking_cannot_be_paid |
| W1 | PASS | Success settles payment |  |
| W2 | PASS | Duplicate x3 |  |
| W3 | PASS | Same event_id, different payload |  |
| W4 | PASS | Failure settles payment |  |
| W5 | PASS | Late failure after success |  |
| W6 | PASS | Success after cancel |  |
| W7 | PASS | Amount mismatch |  |
| W8 | PASS | Unknown provider_reference |  |
| W9 | PASS | Unknown event_type |  |
| W10 | PASS | Invalid signature |  |
| W11 | PASS | Missing signature |  |
| W12 | PASS | Stale timestamp |  |
| W13 | PASS | Malformed payload |  |
| W14 | PASS | Body tampered after signing |  |
| W15 | PASS | Concurrent duplicates |  |
| W16 | PASS | GET webhook not allowed |  |
| X1 | PASS | Envelope audit |  |
| X2 | PASS | No secrets in responses |  |
| X3 | PASS | Login throttling |  |
| X4 | PASS | Logs are structured |  |

## Skipped

- **AU18** covered by pytest: test_expired_access_token_is_rejected
- **B25** covered by pytest: test_cancel_follows_the_state_machine
- **P19** covered by pytest: test_expired_booking_cannot_be_paid
