#!/usr/bin/env python
"""Black-box HTTP checks against a running EVE Healthcare stack.

Exit status is non-zero when any case fails. SKIP does not fail the run.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")
PASSWORD = "Str0ng!Pass#1"
REPORT_PATH = ROOT / "docs" / "API_TEST_REPORT.md"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


class Fail(Exception):
    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(f"{expected} != {actual}")


class Skip(Exception):
    def __init__(self, pytest_name: str):
        self.pytest_name = pytest_name
        super().__init__(pytest_name)


@dataclass
class Exchange:
    case_id: str
    status: int
    text: str
    content_type: str
    data: object


@dataclass
class Result:
    case_id: str
    label: str
    status: str
    detail: str = ""
    expected: str = ""
    actual: str = ""


@dataclass
class Clock:
    stamp: int
    _extra: int = 0

    def at(self, *, days: int, hour: int, minute: int = 0) -> str:
        today = datetime.now(IST).date()
        day = today + timedelta(days=days)
        moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
        return moment.isoformat()

    def unique(self) -> str:
        total = 12 * 60 + self._extra * 20
        self._extra += 1
        hour, minute = divmod(total, 60)
        if hour > 20:
            raise RuntimeError("Ran out of appointment slots inside operating hours.")
        return self.at(days=1, hour=hour, minute=minute)


def _enable_windows_color() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError, ValueError):
        return


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _sign(raw: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip()


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_response(raw: httpx.Response, case_id: str) -> Exchange:
    try:
        data = raw.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        data = None
    return Exchange(
        case_id=case_id,
        status=raw.status_code,
        text=raw.text,
        content_type=raw.headers.get("content-type", ""),
        data=data,
    )


class Runner:
    def __init__(self, base_url: str, flush_throttle: bool):
        self.base_url = base_url.rstrip("/")
        self.flush_throttle = flush_throttle
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)
        self.clock = Clock(stamp=int(time.time()))
        self.results: list[Result] = []
        self.exchanges: list[Exchange] = []
        self.current_case = ""
        self.secret = os.environ.get("WEBHOOK_SECRET", "")
        self.admin_email = os.environ.get("ADMIN_EMAIL", "admin@eve.test")
        self.admin_password = os.environ.get("ADMIN_PASSWORD", "Clinic#Host2026")
        self.email_a = f"user_a_{self.clock.stamp}@test.dev"
        self.email_b = f"user_b_{self.clock.stamp}@test.dev"
        self.token_a = ""
        self.token_b = ""
        self.refresh_a = ""
        self.admin = ""
        self.cid = ""
        self.tid = ""
        self.price = Decimal("0")
        self.xray_id = ""
        self.urine_id = ""
        self.catalogue: dict[str, str] = {}
        self.new_centre = ""
        self.added_test = ""
        self.b1 = ""
        self.b2 = ""
        self.b3 = ""
        self.p1 = ""
        self.p1_key = ""
        self.p17 = ""
        self.p17_ref = ""
        self.p17_amount = ""
        self.b5 = ""
        self.w1_payload: dict = {}
        self.slot_1 = self.clock.at(days=1, hour=10)
        self.slot_2 = self.clock.at(days=1, hour=11)
        self._control_booking = ""
        self._control_payments = 0

    def close(self) -> None:
        self.client.close()

    def case(self, case_id: str, label: str, fn) -> None:
        self.current_case = case_id
        try:
            detail = fn() or ""
        except Skip as exc:
            self._finish("SKIP", case_id, label, detail=f"covered by pytest: {exc.pytest_name}")
        except Fail as exc:
            self._finish(
                "FAIL",
                case_id,
                label,
                expected=exc.expected,
                actual=exc.actual,
            )
        except Exception as exc:
            self._finish("FAIL", case_id, label, expected="case completed", actual=repr(exc))
        else:
            self._finish("PASS", case_id, label, detail=str(detail))

    def _finish(
        self,
        status: str,
        case_id: str,
        label: str,
        *,
        detail: str = "",
        expected: str = "",
        actual: str = "",
    ) -> None:
        self.results.append(
            Result(case_id, label, status, detail=detail, expected=expected, actual=actual)
        )
        color = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}[status]
        suffix = f"  {detail}" if detail and status != "FAIL" else ""
        print(f"{color}{status}{RESET}  {case_id:<4}  {label}{suffix}", flush=True)

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: object | None = None,
        content: bytes | None = None,
        headers: dict | None = None,
        params: dict | None = None,
        retry: bool = True,
    ) -> Exchange:
        extra = dict(headers or {})
        if token:
            extra["Authorization"] = f"Bearer {token}"
        if content is None and json_body is not None and "Content-Type" not in extra:
            extra["Content-Type"] = "application/json"
        attempt = 0
        while True:
            kwargs: dict = {"headers": extra, "params": params}
            if content is not None:
                kwargs["content"] = content
            elif json_body is not None:
                kwargs["json"] = json_body
            raw = self.client.request(method, path, **kwargs)
            parsed = _parse_response(raw, self.current_case)
            parsed_headers = raw.headers
            self.exchanges.append(parsed)
            if (
                retry
                and self.current_case != "X3"
                and parsed.status == 429
                and attempt < 3
                and isinstance(parsed.data, dict)
            ):
                wait = 60.0
                details = (parsed.data.get("error") or {}).get("details") or {}
                if isinstance(details, dict) and details.get("wait_seconds") is not None:
                    wait = float(details["wait_seconds"])
                pause = min(wait, 65.0) + 0.3
                print(
                    f"       waiting {pause:.0f}s for throttle before retrying {self.current_case}",
                    flush=True,
                )
                time.sleep(pause)
                attempt += 1
                continue
            return _Bound(parsed, parsed_headers)

    def expect(self, ok: bool, expected: str, actual: object) -> None:
        if not ok:
            raise Fail(expected, _clip(actual))

    def expect_status(self, resp: Exchange, status: int) -> None:
        if resp.status != status:
            raise Fail(f"HTTP {status}", f"HTTP {resp.status} {_clip(resp.text)}")

    def expect_error(
        self,
        resp: Exchange,
        status: int,
        code: str | None = None,
        fields: tuple[str, ...] = (),
    ) -> dict:
        self.expect_status(resp, status)
        self._expect_envelope(resp)
        err = resp.data["error"]  # type: ignore[index]
        if code is not None:
            self.expect(err["code"] == code, code, err["code"])
        details = err.get("details") or {}
        if not isinstance(details, dict):
            raise Fail(f"details object with {fields}", details)
        for name in fields:
            self.expect(name in details, f"details.{name}", details)
        return err

    def _expect_envelope(self, resp: Exchange) -> None:
        ctype = (resp.content_type or "").lower()
        if "html" in ctype or resp.text.lstrip().lower().startswith("<!doctype html"):
            raise Fail("JSON error envelope", f"content-type {resp.content_type}")
        body = resp.data
        if not isinstance(body, dict) or "error" not in body or not isinstance(body["error"], dict):
            raise Fail('{"error": {"code", "message", "details"}}', _clip(resp.text))
        err = body["error"]
        if "code" not in err or "message" not in err or "details" not in err:
            raise Fail("error.code, error.message, error.details", err)
        if not isinstance(err["code"], str) or not err["code"]:
            raise Fail("error.code string", err.get("code"))
        if not isinstance(err["message"], str) or not err["message"]:
            raise Fail("error.message string", err.get("message"))

    def book(self, when: str, *, centre: str | None = None, test: str | None = None, amount=None):
        body = {
            "centre_id": centre or self.cid,
            "test_id": test or self.tid,
            "appointment_at": when,
        }
        if amount is not None:
            body["amount"] = amount
        return self.request("POST", "/bookings/", token=self.token_a, json_body=body)

    def pay(
        self,
        booking_id: str,
        outcome: str,
        *,
        token: str | None = None,
        key: str | None = None,
        include_key: bool = True,
        amount=None,
    ):
        body: dict = {"booking_id": booking_id, "simulate_outcome": outcome}
        if amount is not None:
            body["amount"] = amount
        headers = {}
        used = key or str(uuid.uuid4())
        if include_key:
            headers["Idempotency-Key"] = used
        resp = self.request(
            "POST",
            "/payments/",
            token=self.token_a if token is None else token,
            json_body=body,
            headers=headers,
        )
        return resp, used

    def new_booking(self) -> str:
        resp = self.book(self.clock.unique())
        self.expect_status(resp, 201)
        return resp.data["id"]  # type: ignore[index]

    def pending_payment(self) -> tuple[str, str, str, str]:
        booking_id = self.new_booking()
        resp, _key = self.pay(booking_id, "PENDING")
        self.expect_status(resp, 201)
        data = resp.data
        return booking_id, data["id"], data["provider_reference"], str(data["amount"])  # type: ignore[index]

    def webhook(
        self,
        payload: dict,
        *,
        timestamp: str | None = None,
        signature: str | None = None,
        include_signature: bool = True,
        raw: bytes | None = None,
    ) -> Exchange:
        body = raw if raw is not None else _canonical(payload)
        stamp = timestamp if timestamp is not None else str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Webhook-Timestamp": stamp}
        if include_signature:
            headers["X-Webhook-Signature"] = signature or _sign(body, self.secret)
        return self.request(
            "POST",
            "/payments/webhook/",
            content=body,
            headers=headers,
            retry=False,
        )

    def event_state(self, event_id: str) -> dict:
        script = (
            "import json; "
            "from apps.payments.models import WebhookEvent; "
            f"qs = WebhookEvent.objects.filter(event_id={event_id!r}); "
            "row = qs.first(); "
            "print('SMOKE_JSON:' + json.dumps({'count': qs.count(), "
            "'status': None if row is None else row.processing_status}))"
        )
        completed = _compose("exec", "-T", "web", "python", "manage.py", "shell", "-c", script)
        if completed.returncode != 0:
            raise Fail("django shell", _clip(completed.stderr or completed.stdout))
        for line in reversed((completed.stdout or "").splitlines()):
            if "SMOKE_JSON:" in line:
                return json.loads(line.split("SMOKE_JSON:", 1)[1])
        raise Fail("SMOKE_JSON from shell", _clip(completed.stdout))

    def poll(self, expected: str, fn) -> None:
        deadline = time.monotonic() + 10
        last = None
        while True:
            last = fn()
            if last is True:
                return
            if time.monotonic() >= deadline:
                raise Fail(expected, _clip(last))
            time.sleep(0.25)

    def ensure_admin(self) -> None:
        if self.admin:
            return
        resp = self.request(
            "POST",
            "/auth/login/",
            json_body={"email": self.admin_email, "password": self.admin_password},
        )
        self.expect_status(resp, 200)
        self.admin = resp.data["access"]  # type: ignore[index]

    def load_catalogue(self) -> None:
        if self.catalogue:
            return
        resp = self.request("GET", "/tests/", params={"page_size": 100})
        self.expect_status(resp, 200)
        self.catalogue = {row["code"]: row["id"] for row in resp.data["results"]}  # type: ignore[index]
        self.xray_id = self.catalogue["XRAY_CHEST"]
        self.urine_id = self.catalogue["URINE"]

    def run(self) -> int:
        if not self.secret:
            print("WEBHOOK_SECRET is empty. Set it in .env.", file=sys.stderr)
            return 2
        if self.flush_throttle:
            flushed = _compose("exec", "-T", "redis", "redis-cli", "FLUSHDB")
            if flushed.returncode != 0:
                print(_clip(flushed.stderr or flushed.stdout), file=sys.stderr)
                return 2
            print("Flushed Redis throttle keys.", flush=True)
        self.section_h()
        self.section_au()
        self.section_c()
        self.section_b()
        self.section_p()
        self.section_w()
        self.section_x()
        self.write_report()
        self.print_summary()
        failed = sum(1 for row in self.results if row.status == "FAIL")
        return 1 if failed else 0

    def section_h(self) -> None:
        self.case("H1", "Health check", self.h1)
        self.case("H2", "Swagger UI loads", self.h2)
        self.case("H3", "OpenAPI schema", self.h3)
        self.case("H4", "Request ID header", self.h4)
        self.case("H5", "Unknown route", self.h5)
        self.case("H6", "Wrong method", self.h6)

    def h1(self) -> None:
        resp = self.request("GET", "/health/")
        self.expect_status(resp, 200)
        self.expect(
            resp.data == {"status": "ok", "db": "ok", "cache": "ok"},
            "status=ok db=ok cache=ok",
            resp.data,
        )

    def h2(self) -> None:
        resp = self.request("GET", "/docs/")
        self.expect_status(resp, 200)
        self.expect("html" in resp.content_type.lower() or "<html" in resp.text.lower(), "HTML", resp.content_type)

    def h3(self) -> None:
        resp = self.request("GET", "/schema/")
        self.expect_status(resp, 200)
        self.expect("/payments/webhook/" in resp.text, "schema contains /payments/webhook/", "path missing")

    def h4(self) -> None:
        resp = self.request("GET", "/health/", headers={"X-Request-ID": "smoke-123"})
        self.expect_status(resp, 200)
        header = resp.headers.get("X-Request-ID")  # type: ignore[attr-defined]
        self.expect(header == "smoke-123", "X-Request-ID: smoke-123", header)

    def h5(self) -> None:
        resp = self.request("GET", "/does-not-exist/")
        self.expect_error(resp, 404, "NOT_FOUND")

    def h6(self) -> None:
        resp = self.request("PUT", "/health/")
        self.expect_error(resp, 405, "METHOD_NOT_ALLOWED")

    def section_au(self) -> None:
        self.case("AU1", "Signup success", self.au1)
        self.case("AU2", "Signup user B", self.au2)
        self.case("AU3", "Duplicate email, different case", self.au3)
        self.case("AU4", "Weak password", self.au4)
        self.case("AU5", "Missing email", self.au5)
        self.case("AU6", "Invalid email format", self.au6)
        self.case("AU7", "Invalid phone", self.au7)
        self.case("AU8", "Empty body", self.au8)
        self.case("AU9", "Malformed JSON", self.au9)
        self.case("AU10", "Login success", self.au10)
        self.case("AU11", "Wrong password", self.au11)
        self.case("AU12", "Unknown email", self.au12)
        self.case("AU13", "Me with token", self.au13)
        self.case("AU14", "Me without token", self.au14)
        self.case("AU15", "Me with garbage token", self.au15)
        self.case("AU16", "Refresh token", self.au16)
        self.case("AU17", "Reuse rotated refresh", self.au17)
        self.case("AU18", "Expired access token", self.au18)

    def _signup(self, email: str, **overrides):
        body = {
            "email": email,
            "password": PASSWORD,
            "full_name": "User A",
            "phone": "9876543210",
        }
        body.update(overrides)
        return self.request("POST", "/auth/signup/", json_body=body)

    def au1(self) -> None:
        resp = self._signup(self.email_a)
        self.expect_status(resp, 201)
        user = resp.data["user"]  # type: ignore[index]
        self.expect("password" not in user, "no password field", list(user))
        self.expect(bool(resp.data["access"] and resp.data["refresh"]), "access and refresh", resp.data)  # type: ignore[index]
        self.expect(user["email"] == self.email_a, self.email_a, user["email"])
        self.token_a = resp.data["access"]  # type: ignore[index]

    def au2(self) -> None:
        resp = self._signup(self.email_b, full_name="User B", phone="9123456780")
        self.expect_status(resp, 201)
        self.token_b = resp.data["access"]  # type: ignore[index]

    def au3(self) -> None:
        resp = self._signup(self.email_a.upper(), full_name="User A2", phone="9988776655")
        self.expect_error(resp, 409, "EMAIL_ALREADY_REGISTERED")

    def au4(self) -> None:
        resp = self._signup(f"weak_{self.clock.stamp}@test.dev", password="123")
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("password",))

    def au5(self) -> None:
        resp = self.request(
            "POST",
            "/auth/signup/",
            json_body={"password": PASSWORD, "full_name": "User A", "phone": "9876543210"},
        )
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("email",))

    def au6(self) -> None:
        resp = self._signup("not-an-email")
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("email",))

    def au7(self) -> None:
        resp = self._signup(f"phone_{self.clock.stamp}@test.dev", phone="12345")
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("phone",))

    def au8(self) -> None:
        resp = self.request("POST", "/auth/signup/", json_body={})
        self.expect_error(resp, 400, "VALIDATION_ERROR")

    def au9(self) -> None:
        resp = self.request(
            "POST",
            "/auth/signup/",
            content=b'{"email":',
            headers={"Content-Type": "application/json"},
        )
        self.expect_error(resp, 400, "PARSE_ERROR")

    def au10(self) -> None:
        resp = self.request(
            "POST",
            "/auth/login/",
            json_body={"email": self.email_a, "password": PASSWORD},
        )
        self.expect_status(resp, 200)
        self.expect(bool(resp.data["access"] and resp.data["refresh"]), "access and refresh", resp.data)  # type: ignore[index]
        self.token_a = resp.data["access"]  # type: ignore[index]
        self.refresh_a = resp.data["refresh"]  # type: ignore[index]

    def au11(self) -> str:
        resp = self.request(
            "POST",
            "/auth/login/",
            json_body={"email": self.email_a, "password": "wrong-password"},
        )
        err = self.expect_error(resp, 401, "INVALID_CREDENTIALS")
        self._au11_message = err["message"]
        return ""

    def au12(self) -> None:
        resp = self.request(
            "POST",
            "/auth/login/",
            json_body={"email": f"nobody_{self.clock.stamp}@test.dev", "password": PASSWORD},
        )
        err = self.expect_error(resp, 401, "INVALID_CREDENTIALS")
        self.expect(err["message"] == self._au11_message, self._au11_message, err["message"])

    def au13(self) -> None:
        resp = self.request("GET", "/auth/me/", token=self.token_a)
        self.expect_status(resp, 200)
        self.expect(resp.data["email"] == self.email_a, self.email_a, resp.data.get("email"))  # type: ignore[union-attr]
        self.expect("password" not in resp.data, "no password field", list(resp.data))  # type: ignore[arg-type]

    def au14(self) -> None:
        resp = self.request("GET", "/auth/me/")
        self.expect_error(resp, 401, "NOT_AUTHENTICATED")

    def au15(self) -> None:
        resp = self.request("GET", "/auth/me/", headers={"Authorization": "Bearer abc.def.ghi"})
        self.expect_error(resp, 401, "AUTHENTICATION_FAILED")

    def au16(self) -> None:
        old = self.refresh_a
        resp = self.request("POST", "/auth/token/refresh/", json_body={"refresh": old})
        self.expect_status(resp, 200)
        self.expect(bool(resp.data["access"]), "new access", resp.data)  # type: ignore[index]
        self.expect(resp.data["refresh"] != old, "rotated refresh", resp.data.get("refresh"))  # type: ignore[union-attr]
        self._old_refresh = old
        self.token_a = resp.data["access"]  # type: ignore[index]

    def au17(self) -> None:
        resp = self.request(
            "POST",
            "/auth/token/refresh/",
            json_body={"refresh": self._old_refresh},
        )
        self.expect_error(resp, 401, "AUTHENTICATION_FAILED")

    def au18(self) -> None:
        raise Skip("test_expired_access_token_is_rejected")

    def section_c(self) -> None:
        self.case("C1", "List centres", self.c1)
        self.case("C2", "Filter by city", self.c2)
        self.case("C3", "Filter by test", self.c3)
        self.case("C4", "Search by name", self.c4)
        self.case("C5", "Page size", self.c5)
        self.case("C6", "Oversized page size", self.c6)
        self.case("C7", "Page out of range", self.c7)
        self.case("C8", "Centre detail", self.c8)
        self.case("C9", "Centre not found", self.c9)
        self.case("C10", "Centre tests", self.c10)
        self.case("C11", "Test catalogue", self.c11)
        self.case("C12", "Anonymous create", self.c12)
        self.case("C13", "Non-admin create", self.c13)
        self.case("C14", "Admin create centre", self.c14)
        self.case("C15", "Duplicate name + city", self.c15)
        self.case("C16", "Invalid pincode", self.c16)
        self.case("C17", "Add test to centre", self.c17)
        self.case("C18", "Zero/negative price", self.c18)
        self.case("C19", "Same test twice", self.c19)
        self.case("C20", "Update price, cache invalidated", self.c20)
        self.case("C21", "Soft delete", self.c21)

    def _page(self, path: str, params: dict | None = None) -> Exchange:
        return self.request("GET", path, params=params)

    def c1(self) -> None:
        resp = self._page("/centres/")
        self.expect_status(resp, 200)
        for key in ("count", "next", "previous", "results"):
            self.expect(key in resp.data, f"paginated {key}", resp.data)  # type: ignore[arg-type]
        self.expect(resp.data["count"] >= 5, "count >= 5", resp.data["count"])  # type: ignore[index]

    def c2(self) -> None:
        resp = self._page("/centres/", {"city": "Guwahati", "page_size": 100})
        self.expect_status(resp, 200)
        rows = resp.data["results"]  # type: ignore[index]
        self.expect(bool(rows), "at least one Guwahati centre", rows)
        self.expect(all(row["city"] == "Guwahati" for row in rows), "every city is Guwahati", rows)
        match = next(row for row in rows if row["name"] == "EVE Diagnostics Guwahati")
        self.cid = match["id"]

    def c3(self) -> None:
        resp = self._page("/centres/", {"test_code": "CBC", "page_size": 100})
        self.expect_status(resp, 200)
        rows = resp.data["results"]  # type: ignore[index]
        self.expect(bool(rows), "at least one centre", rows)
        for row in rows:
            tests = self.request("GET", f"/centres/{row['id']}/tests/")
            self.expect_status(tests, 200)
            codes = [item["code"] for item in tests.data]  # type: ignore[union-attr]
            self.expect("CBC" in codes, f"{row['name']} offers CBC", codes)

    def c4(self) -> None:
        resp = self._page("/centres/", {"search": "Guwahati", "page_size": 100})
        self.expect_status(resp, 200)
        rows = resp.data["results"]  # type: ignore[index]
        self.expect(bool(rows), "matching results", rows)
        self.expect(
            all("guwahati" in row["name"].lower() for row in rows),
            "names contain Guwahati",
            [row["name"] for row in rows],
        )

    def c5(self) -> None:
        resp = self._page("/centres/", {"page_size": 2})
        self.expect_status(resp, 200)
        self.expect(len(resp.data["results"]) == 2, "2 results", len(resp.data["results"]))  # type: ignore[index]
        self.expect(resp.data["next"] is not None, "next is not null", resp.data["next"])  # type: ignore[index]

    def c6(self) -> None:
        resp = self._page("/centres/", {"page_size": 10000})
        self.expect_status(resp, 200)
        self.expect(len(resp.data["results"]) <= 100, "<= 100 results", len(resp.data["results"]))  # type: ignore[index]

    def c7(self) -> None:
        resp = self._page("/centres/", {"page": 9999})
        self.expect_error(resp, 404, "NOT_FOUND")

    def c8(self) -> None:
        resp = self.request("GET", f"/centres/{self.cid}/")
        self.expect_status(resp, 200)
        tests = resp.data["tests"]  # type: ignore[index]
        self.expect(bool(tests) and all("price" in row for row in tests), "nested tests with price", tests)
        cbc = next(row for row in tests if row["code"] == "CBC")
        self.tid = cbc["id"]
        self.price = _money(cbc["price"])

    def c9(self) -> None:
        resp = self.request("GET", f"/centres/{uuid.uuid4()}/")
        self.expect_error(resp, 404, "NOT_FOUND")

    def c10(self) -> None:
        resp = self.request("GET", f"/centres/{self.cid}/tests/")
        self.expect_status(resp, 200)
        self.expect(
            bool(resp.data) and all("price" in row and "code" in row for row in resp.data),  # type: ignore[union-attr]
            "tests and prices",
            resp.data,
        )

    def c11(self) -> None:
        resp = self._page("/tests/", {"search": "thyroid"})
        self.expect_status(resp, 200)
        names = [row["name"] for row in resp.data["results"]]  # type: ignore[index]
        self.expect("Thyroid Profile" in names, "Thyroid Profile", names)

    def _centre_body(self, **overrides) -> dict:
        body = {
            "name": f"Smoke Lab {self.clock.stamp}",
            "address": "1 Smoke Road",
            "city": "Guwahati",
            "pincode": "781001",
            "phone": "03610001111",
        }
        body.update(overrides)
        return body

    def c12(self) -> None:
        resp = self.request("POST", "/centres/", json_body=self._centre_body(name="Anon Lab"))
        self.expect_error(resp, 401, "NOT_AUTHENTICATED")

    def c13(self) -> None:
        resp = self.request(
            "POST",
            "/centres/",
            token=self.token_a,
            json_body=self._centre_body(name="Patient Lab"),
        )
        self.expect_error(resp, 403, "PERMISSION_DENIED")

    def c14(self) -> None:
        self.ensure_admin()
        self._centre = self._centre_body()
        resp = self.request("POST", "/centres/", token=self.admin, json_body=self._centre)
        self.expect_status(resp, 201)
        self.new_centre = resp.data["id"]  # type: ignore[index]

    def c15(self) -> None:
        resp = self.request("POST", "/centres/", token=self.admin, json_body=self._centre)
        self.expect_error(resp, 409, "CENTRE_ALREADY_EXISTS")

    def c16(self) -> None:
        body = self._centre_body(name=f"Bad Pin {self.clock.stamp}", pincode="12")
        resp = self.request("POST", "/centres/", token=self.admin, json_body=body)
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("pincode",))

    def c17(self) -> None:
        self.load_catalogue()
        self.added_test = self.catalogue["CBC"]
        resp = self.request(
            "POST",
            f"/centres/{self.new_centre}/tests/",
            token=self.admin,
            json_body={"test_id": self.added_test, "price": "450.00"},
        )
        self.expect_status(resp, 201)

    def c18(self) -> None:
        for code, price in (("LFT", "0"), ("KFT", "-10")):
            resp = self.request(
                "POST",
                f"/centres/{self.new_centre}/tests/",
                token=self.admin,
                json_body={"test_id": self.catalogue[code], "price": price},
            )
            self.expect_error(resp, 400, "VALIDATION_ERROR", ("price",))

    def c19(self) -> None:
        resp = self.request(
            "POST",
            f"/centres/{self.new_centre}/tests/",
            token=self.admin,
            json_body={"test_id": self.added_test, "price": "450.00"},
        )
        self.expect_error(resp, 409, "TEST_ALREADY_OFFERED")

    def c20(self) -> None:
        patched = self.request(
            "PATCH",
            f"/centres/{self.new_centre}/tests/{self.added_test}/",
            token=self.admin,
            json_body={"price": "500.00"},
        )
        self.expect_status(patched, 200)
        detail = self.request("GET", f"/centres/{self.new_centre}/")
        self.expect_status(detail, 200)
        row = next(item for item in detail.data["tests"] if item["id"] == self.added_test)  # type: ignore[index]
        self.expect(_money(row["price"]) == Decimal("500.00"), "500.00", row["price"])

    def c21(self) -> None:
        deleted = self.request("DELETE", f"/centres/{self.new_centre}/", token=self.admin)
        self.expect_status(deleted, 204)
        listed = self._page("/centres/", {"search": self._centre["name"], "page_size": 100})
        self.expect_status(listed, 200)
        ids = [row["id"] for row in listed.data["results"]]  # type: ignore[index]
        self.expect(self.new_centre not in ids, "absent from list", ids)
        detail = self.request("GET", f"/centres/{self.new_centre}/")
        self.expect_error(detail, 404, "NOT_FOUND")

    def section_b(self) -> None:
        self.load_catalogue()
        self.case("B1", "Create booking", self.b1_case)
        self.case("B2", "Client amount ignored", self.b2_case)
        self.case("B3", "Past appointment", self.b3_case)
        self.case("B4", "Beyond 90 days", self.b4_case)
        self.case("B5", "Outside operating hours", self.b5_case)
        self.case("B6", "Test not offered at centre", self.b6_case)
        self.case("B7", "Test unavailable at centre", self.b7_case)
        self.case("B8", "Inactive centre", self.b8_case)
        self.case("B9", "Nonexistent centre", self.b9_case)
        self.case("B10", "Missing fields", self.b10_case)
        self.case("B11", "Bad datetime", self.b11_case)
        self.case("B12", "Duplicate active booking", self.b12_case)
        self.case("B13", "No token", self.b13_case)
        self.case("B14", "List own only", self.b14_case)
        self.case("B15", "Filter by status", self.b15_case)
        self.case("B16", "Get own booking", self.b16_case)
        self.case("B17", "Get other's booking", self.b17_case)
        self.case("B18", "Malformed UUID", self.b18_case)
        self.case("B19", "Cancel pending", self.b19_case)
        self.case("B20", "Cancel again", self.b20_case)
        self.case("B21", "Cancel other's booking", self.b21_case)
        self.case("B22", "Rebook cancelled slot", self.b22_case)
        self.case("B23", "Price snapshot", self.b23_case)
        self.case("B25", "Cancel confirmed < 2h away", self.b25_case)

    def b1_case(self) -> None:
        resp = self.book(self.slot_1)
        self.expect_status(resp, 201)
        self.expect(resp.data["status"] == "PENDING", "PENDING", resp.data["status"])  # type: ignore[index]
        self.expect(_money(resp.data["amount"]) == self.price, str(self.price), resp.data["amount"])  # type: ignore[index]
        self.b1 = resp.data["id"]  # type: ignore[index]

    def b2_case(self) -> None:
        resp = self.book(self.slot_2, amount="1.00")
        self.expect_status(resp, 201)
        self.expect(_money(resp.data["amount"]) == self.price, str(self.price), resp.data["amount"])  # type: ignore[index]
        self.b2 = resp.data["id"]  # type: ignore[index]

    def b3_case(self) -> None:
        resp = self.book(self.clock.at(days=-1, hour=10))
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("appointment_at",))

    def b4_case(self) -> None:
        resp = self.book(self.clock.at(days=120, hour=10))
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("appointment_at",))

    def b5_case(self) -> None:
        resp = self.book(self.clock.at(days=1, hour=22))
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("appointment_at",))

    def b6_case(self) -> None:
        resp = self.book(self.clock.unique(), test=self.xray_id)
        self.expect_error(resp, 400, "TEST_NOT_OFFERED_AT_CENTRE")

    def b7_case(self) -> None:
        self.ensure_admin()
        path = f"/centres/{self.cid}/tests/{self.urine_id}/"
        off = self.request("PATCH", path, token=self.admin, json_body={"is_available": False})
        self.expect_status(off, 200)
        try:
            resp = self.book(self.clock.unique(), test=self.urine_id)
            self.expect_error(resp, 400, "TEST_UNAVAILABLE")
        finally:
            self.request("PATCH", path, token=self.admin, json_body={"is_available": True})

    def b8_case(self) -> None:
        resp = self.book(self.clock.unique(), centre=self.new_centre, test=self.added_test)
        self.expect_error(resp, 400, "CENTRE_INACTIVE")

    def b9_case(self) -> None:
        resp = self.book(self.clock.unique(), centre=str(uuid.uuid4()))
        self.expect_error(resp, 404, "NOT_FOUND")

    def b10_case(self) -> None:
        resp = self.request("POST", "/bookings/", token=self.token_a, json_body={})
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("centre_id", "test_id", "appointment_at"))

    def b11_case(self) -> None:
        resp = self.request(
            "POST",
            "/bookings/",
            token=self.token_a,
            json_body={"centre_id": self.cid, "test_id": self.tid, "appointment_at": "tomorrow"},
        )
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("appointment_at",))

    def b12_case(self) -> None:
        resp = self.book(self.slot_1)
        self.expect_error(resp, 409, "DUPLICATE_BOOKING")

    def b13_case(self) -> None:
        resp = self.request(
            "POST",
            "/bookings/",
            json_body={
                "centre_id": self.cid,
                "test_id": self.tid,
                "appointment_at": self.slot_1,
            },
        )
        self.expect_error(resp, 401, "NOT_AUTHENTICATED")

    def b14_case(self) -> None:
        resp = self.request("GET", "/bookings/", token=self.token_b)
        self.expect_status(resp, 200)
        self.expect(resp.data["count"] == 0, "count 0", resp.data["count"])  # type: ignore[index]

    def b15_case(self) -> None:
        resp = self.request("GET", "/bookings/", token=self.token_a, params={"status": "PENDING"})
        self.expect_status(resp, 200)
        rows = resp.data["results"]  # type: ignore[index]
        self.expect(bool(rows), "pending bookings", rows)
        self.expect(all(row["status"] == "PENDING" for row in rows), "all PENDING", rows)

    def b16_case(self) -> None:
        resp = self.request("GET", f"/bookings/{self.b1}/", token=self.token_a)
        self.expect_status(resp, 200)
        self.expect(resp.data["id"] == self.b1, self.b1, resp.data.get("id"))  # type: ignore[union-attr]

    def b17_case(self) -> None:
        resp = self.request("GET", f"/bookings/{self.b1}/", token=self.token_b)
        self.expect_error(resp, 404, "NOT_FOUND")

    def b18_case(self) -> None:
        resp = self.request("GET", "/bookings/not-a-uuid/", token=self.token_a)
        self.expect_error(resp, 404, "NOT_FOUND")

    def b19_case(self) -> None:
        resp = self.request(
            "POST",
            f"/bookings/{self.b2}/cancel/",
            token=self.token_a,
            json_body={"reason": "test"},
        )
        self.expect_status(resp, 200)
        self.expect(resp.data["status"] == "CANCELLED", "CANCELLED", resp.data["status"])  # type: ignore[index]
        self.expect(bool(resp.data["cancelled_at"]), "cancelled_at set", resp.data["cancelled_at"])  # type: ignore[index]

    def b20_case(self) -> None:
        resp = self.request(
            "POST",
            f"/bookings/{self.b2}/cancel/",
            token=self.token_a,
            json_body={"reason": "test"},
        )
        self.expect_error(resp, 409, "INVALID_STATE_TRANSITION")

    def b21_case(self) -> None:
        resp = self.request(
            "POST",
            f"/bookings/{self.b1}/cancel/",
            token=self.token_b,
            json_body={"reason": "nope"},
        )
        self.expect_error(resp, 404, "NOT_FOUND")

    def b22_case(self) -> None:
        resp = self.book(self.slot_2)
        self.expect_status(resp, 201)
        self.expect(resp.data["status"] == "PENDING", "PENDING", resp.data["status"])  # type: ignore[index]

    def b23_case(self) -> None:
        self.ensure_admin()
        path = f"/centres/{self.cid}/tests/{self.tid}/"
        original = f"{self.price:.2f}"
        patched = self.request("PATCH", path, token=self.admin, json_body={"price": "510.00"})
        self.expect_status(patched, 200)
        try:
            got = self.request("GET", f"/bookings/{self.b1}/", token=self.token_a)
            self.expect_status(got, 200)
            self.expect(_money(got.data["amount"]) == self.price, str(self.price), got.data["amount"])  # type: ignore[index]
        finally:
            self.request("PATCH", path, token=self.admin, json_body={"price": original})

    def b24_case(self) -> None:
        resp = self.request(
            "POST",
            f"/bookings/{self.b1}/cancel/",
            token=self.token_a,
            json_body={"reason": "confirmed cancel"},
        )
        self.expect_status(resp, 200)
        self.expect(resp.data["status"] == "CANCELLED", "CANCELLED", resp.data["status"])  # type: ignore[index]

    def b25_case(self) -> None:
        raise Skip("test_cancel_follows_the_state_machine")

    def section_p(self) -> None:
        self.case("P1", "Success", self.p1_case)
        self.case("P2", "Failure", self.p2_case)
        self.case("P3", "Missing Idempotency-Key", self.p3_case)
        self.case("P4", "Idempotent replay", self.p4_case)
        self.case("P5", "Key reused, different booking", self.p5_case)
        self.case("P6", "Pay confirmed booking", self.p6_case)
        self.case("B24", "Cancel confirmed > 2h away", self.b24_case)
        self.case("P7", "Pay failed booking", self.p7_case)
        self.case("P8", "Pay cancelled booking", self.p8_case)
        self.case("P9", "Pay other's booking", self.p9_case)
        self.case("P10", "Nonexistent booking", self.p10_case)
        self.case("P11", "Malformed booking_id", self.p11_case)
        self.case("P12", "Invalid outcome", self.p12_case)
        self.case("P13", "Client amount ignored", self.p13_case)
        self.case("P14", "No token", self.p14_case)
        self.case("P15", "Get own payment / other's", self.p15_case)
        self.case("P16", "Booking payment history", self.p16_case)
        self.case("P17", "Pending outcome", self.p17_case)
        self.case("P18", "Race: parallel payments", self.p18_case)
        self.case("P19", "Pay expired booking", self.p19_case)

    def p1_case(self) -> None:
        resp, key = self.pay(self.b1, "SUCCESS")
        self.expect_status(resp, 201)
        self.expect(resp.data["status"] == "SUCCESS", "SUCCESS", resp.data["status"])  # type: ignore[index]
        self.expect(_money(resp.data["amount"]) == self.price, str(self.price), resp.data["amount"])  # type: ignore[index]
        self.expect(resp.data["booking_status"] == "CONFIRMED", "CONFIRMED", resp.data["booking_status"])  # type: ignore[index]
        self.p1 = resp.data["id"]  # type: ignore[index]
        self.p1_key = key

    def p2_case(self) -> None:
        self.b3 = self.new_booking()
        resp, _key = self.pay(self.b3, "FAILED")
        self.expect_status(resp, 201)
        self.expect(resp.data["status"] == "FAILED", "FAILED", resp.data["status"])  # type: ignore[index]
        self.expect(bool(resp.data["failure_reason"]), "failure_reason set", resp.data["failure_reason"])  # type: ignore[index]
        self.expect(resp.data["booking_status"] == "FAILED", "FAILED", resp.data["booking_status"])  # type: ignore[index]

    def p3_case(self) -> None:
        resp, _key = self.pay(self.b1, "SUCCESS", include_key=False)
        self.expect_error(resp, 400, "IDEMPOTENCY_KEY_REQUIRED")

    def p4_case(self) -> None:
        resp, _key = self.pay(self.b1, "FAILED", key=self.p1_key)
        self.expect_status(resp, 200)
        self.expect(resp.data["id"] == self.p1, self.p1, resp.data.get("id"))  # type: ignore[union-attr]
        history = self.request("GET", f"/bookings/{self.b1}/payments/", token=self.token_a)
        self.expect_status(history, 200)
        self.expect(history.data["count"] == 1, "1 payment", history.data["count"])  # type: ignore[index]

    def p5_case(self) -> None:
        other = self.new_booking()
        resp, _key = self.pay(other, "SUCCESS", key=self.p1_key)
        self.expect_error(resp, 422, "IDEMPOTENCY_KEY_REUSED")

    def p6_case(self) -> None:
        resp, _key = self.pay(self.b1, "SUCCESS")
        self.expect_error(resp, 409, "BOOKING_ALREADY_PAID")

    def p7_case(self) -> None:
        resp, _key = self.pay(self.b3, "SUCCESS")
        self.expect_error(resp, 409, "BOOKING_NOT_PAYABLE")

    def p8_case(self) -> None:
        resp, _key = self.pay(self.b2, "SUCCESS")
        self.expect_error(resp, 409, "BOOKING_NOT_PAYABLE")

    def p9_case(self) -> None:
        resp, _key = self.pay(self.b1, "SUCCESS", token=self.token_b)
        self.expect_error(resp, 404, "NOT_FOUND")

    def p10_case(self) -> None:
        resp, _key = self.pay(str(uuid.uuid4()), "SUCCESS")
        self.expect_error(resp, 404, "NOT_FOUND")

    def p11_case(self) -> None:
        resp = self.request(
            "POST",
            "/payments/",
            token=self.token_a,
            json_body={"booking_id": "abc", "simulate_outcome": "SUCCESS"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("booking_id",))

    def p12_case(self) -> None:
        resp = self.request(
            "POST",
            "/payments/",
            token=self.token_a,
            json_body={"booking_id": self.b1, "simulate_outcome": "MAYBE"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        self.expect_error(resp, 400, "VALIDATION_ERROR", ("simulate_outcome",))

    def p13_case(self) -> None:
        booking_id = self.new_booking()
        resp, _key = self.pay(booking_id, "SUCCESS", amount="1.00")
        self.expect_status(resp, 201)
        self.expect(_money(resp.data["amount"]) == self.price, str(self.price), resp.data["amount"])  # type: ignore[index]

    def p14_case(self) -> None:
        resp = self.request(
            "POST",
            "/payments/",
            json_body={"booking_id": self.b1, "simulate_outcome": "SUCCESS"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        self.expect_error(resp, 401, "NOT_AUTHENTICATED")

    def p15_case(self) -> None:
        own = self.request("GET", f"/payments/{self.p1}/", token=self.token_a)
        self.expect_status(own, 200)
        self.expect(own.data["id"] == self.p1, self.p1, own.data.get("id"))  # type: ignore[union-attr]
        other = self.request("GET", f"/payments/{self.p1}/", token=self.token_b)
        self.expect_error(other, 404, "NOT_FOUND")

    def p16_case(self) -> None:
        resp = self.request("GET", f"/bookings/{self.b3}/payments/", token=self.token_a)
        self.expect_status(resp, 200)
        self.expect(resp.data["count"] == 1, "1 attempt", resp.data["count"])  # type: ignore[index]
        self.expect(resp.data["results"][0]["status"] == "FAILED", "FAILED", resp.data["results"])  # type: ignore[index]

    def p17_case(self) -> None:
        self.b5, self.p17, self.p17_ref, self.p17_amount = self.pending_payment()
        got = self.request("GET", f"/bookings/{self.b5}/", token=self.token_a)
        self.expect_status(got, 200)
        self.expect(got.data["status"] == "PENDING", "booking PENDING", got.data["status"])  # type: ignore[index]
        payment = self.request("GET", f"/payments/{self.p17}/", token=self.token_a)
        self.expect(payment.data["status"] == "INITIATED", "INITIATED", payment.data["status"])  # type: ignore[index]

    def p18_case(self) -> None:
        booking_id = self.new_booking()
        url = f"{self.base_url}/payments/"

        def one(_index: int) -> httpx.Response:
            headers = {
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
                "Idempotency-Key": str(uuid.uuid4()),
            }
            body = {"booking_id": booking_id, "simulate_outcome": "SUCCESS"}
            with httpx.Client(timeout=30.0) as client:
                return client.post(url, json=body, headers=headers)

        responses = self._burst(5, one)
        for raw in responses:
            self.exchanges.append(_parse_response(raw, "P18"))
        codes = sorted(raw.status_code for raw in responses)
        created = [raw for raw in responses if raw.status_code == 201]
        rejected = [raw for raw in responses if raw.status_code != 201]
        self.expect(len(created) == 1, "exactly one 201", codes)
        self.expect(all(raw.status_code == 409 for raw in rejected), "the rest 409", codes)
        self.expect(created[0].json()["status"] == "SUCCESS", "SUCCESS", created[0].text)
        for raw in rejected:
            parsed = _parse_response(raw, "P18")
            self.expect_error(parsed, 409, "BOOKING_ALREADY_PAID")
        history = self.request("GET", f"/bookings/{booking_id}/payments/", token=self.token_a)
        self.expect_status(history, 200)
        self.expect(history.data["count"] == 1, "exactly 1 payment", history.data["count"])  # type: ignore[index]
        self.expect(history.data["results"][0]["status"] == "SUCCESS", "SUCCESS", history.data["results"])  # type: ignore[index]

    def p19_case(self) -> None:
        raise Skip("test_expired_booking_cannot_be_paid")

    def section_w(self) -> None:
        self.case("W1", "Success settles payment", self.w1)
        self.case("W2", "Duplicate x3", self.w2)
        self.case("W3", "Same event_id, different payload", self.w3)
        self.case("W4", "Failure settles payment", self.w4)
        self.case("W5", "Late failure after success", self.w5)
        self.case("W6", "Success after cancel", self.w6)
        self.case("W7", "Amount mismatch", self.w7)
        self.case("W8", "Unknown provider_reference", self.w8)
        self.case("W9", "Unknown event_type", self.w9)
        self.case("W10", "Invalid signature", self.w10)
        self.case("W11", "Missing signature", self.w11)
        self.case("W12", "Stale timestamp", self.w12)
        self.case("W13", "Malformed payload", self.w13)
        self.case("W14", "Body tampered after signing", self.w14)
        self.case("W15", "Concurrent duplicates", self.w15)
        self.case("W16", "GET webhook not allowed", self.w16)

    def _event(self, reference: str, amount: str, event_type: str, event_id: str | None = None) -> dict:
        return {
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": {"amount": amount, "currency": "INR", "provider_reference": reference},
            "event_id": event_id or f"evt_{uuid.uuid4()}",
            "event_type": event_type,
        }

    def w1(self) -> None:
        payload = self._event(self.p17_ref, self.p17_amount, "payment.succeeded")
        self.w1_payload = payload
        resp = self.webhook(payload)
        self.expect_status(resp, 200)
        self.expect(resp.data["status"] == "accepted", "accepted", resp.data)  # type: ignore[index]

        def ready():
            payment = self.request("GET", f"/payments/{self.p17}/", token=self.token_a)
            booking = self.request("GET", f"/bookings/{self.b5}/", token=self.token_a)
            if (
                isinstance(payment.data, dict)
                and payment.data.get("status") == "SUCCESS"
                and isinstance(booking.data, dict)
                and booking.data.get("status") == "CONFIRMED"
            ):
                return True
            return {"payment": getattr(payment, "data", None), "booking": getattr(booking, "data", None)}

        self.poll("payment SUCCESS and booking CONFIRMED", ready)
        state = self.event_state(payload["event_id"])
        self.expect(state["status"] == "PROCESSED" and state["count"] == 1, "PROCESSED x1", state)
        self._control_booking = self.b5
        history = self.request("GET", f"/bookings/{self.b5}/payments/", token=self.token_a)
        self._control_payments = history.data["count"]  # type: ignore[index]

    def w2(self) -> None:
        for _ in range(3):
            resp = self.webhook(self.w1_payload)
            self.expect_status(resp, 200)
            self.expect(resp.data["status"] == "duplicate", "duplicate", resp.data)  # type: ignore[index]
        state = self.event_state(self.w1_payload["event_id"])
        self.expect(state["count"] == 1, "1 WebhookEvent row", state)
        booking = self.request("GET", f"/bookings/{self.b5}/", token=self.token_a)
        self.expect(booking.data["status"] == "CONFIRMED", "CONFIRMED", booking.data["status"])  # type: ignore[index]
        history = self.request("GET", f"/bookings/{self.b5}/payments/", token=self.token_a)
        successes = [row for row in history.data["results"] if row["status"] == "SUCCESS"]  # type: ignore[index]
        self.expect(len(successes) == 1, "1 SUCCESS payment", history.data)  # type: ignore[index]

    def w3(self) -> None:
        payload = self._event(
            self.p17_ref,
            self.p17_amount,
            "payment.failed",
            event_id=self.w1_payload["event_id"],
        )
        resp = self.webhook(payload)
        self.expect_status(resp, 200)
        self.expect(resp.data["status"] == "duplicate", "duplicate", resp.data)  # type: ignore[index]
        payment = self.request("GET", f"/payments/{self.p17}/", token=self.token_a)
        booking = self.request("GET", f"/bookings/{self.b5}/", token=self.token_a)
        self.expect(payment.data["status"] == "SUCCESS", "SUCCESS", payment.data["status"])  # type: ignore[index]
        self.expect(booking.data["status"] == "CONFIRMED", "CONFIRMED", booking.data["status"])  # type: ignore[index]
        self.expect(self.event_state(payload["event_id"])["count"] == 1, "1 row", "changed")

    def w4(self) -> None:
        booking_id, payment_id, reference, amount = self.pending_payment()
        payload = self._event(reference, amount, "payment.failed")
        resp = self.webhook(payload)
        self.expect_status(resp, 200)

        def ready():
            payment = self.request("GET", f"/payments/{payment_id}/", token=self.token_a)
            booking = self.request("GET", f"/bookings/{booking_id}/", token=self.token_a)
            if (
                isinstance(payment.data, dict)
                and payment.data.get("status") == "FAILED"
                and isinstance(booking.data, dict)
                and booking.data.get("status") == "FAILED"
            ):
                return True
            return {"payment": payment.data, "booking": booking.data}

        self.poll("payment FAILED and booking FAILED", ready)
        self.expect(self.event_state(payload["event_id"])["status"] == "PROCESSED", "PROCESSED", "not processed")

    def w5(self) -> None:
        payload = self._event(self.p17_ref, self.p17_amount, "payment.failed")
        resp = self.webhook(payload)
        self.expect_status(resp, 200)

        def ready():
            state = self.event_state(payload["event_id"])
            return True if state.get("status") == "PROCESSED" else state

        self.poll("late failure event PROCESSED", ready)
        payment = self.request("GET", f"/payments/{self.p17}/", token=self.token_a)
        booking = self.request("GET", f"/bookings/{self.b5}/", token=self.token_a)
        self.expect(payment.data["status"] == "SUCCESS", "SUCCESS", payment.data["status"])  # type: ignore[index]
        self.expect(booking.data["status"] == "CONFIRMED", "CONFIRMED", booking.data["status"])  # type: ignore[index]

    def w6(self) -> None:
        booking_id, payment_id, reference, amount = self.pending_payment()
        cancelled = self.request(
            "POST",
            f"/bookings/{booking_id}/cancel/",
            token=self.token_a,
            json_body={"reason": "before webhook"},
        )
        self.expect_status(cancelled, 200)
        payload = self._event(reference, amount, "payment.succeeded")
        resp = self.webhook(payload)
        self.expect_status(resp, 200)

        def ready():
            payment = self.request("GET", f"/payments/{payment_id}/", token=self.token_a)
            booking = self.request("GET", f"/bookings/{booking_id}/", token=self.token_a)
            if (
                isinstance(payment.data, dict)
                and payment.data.get("status") == "SUCCESS"
                and isinstance(booking.data, dict)
                and booking.data.get("status") == "CANCELLED"
            ):
                return True
            return {"payment": payment.data, "booking": booking.data}

        self.poll("payment SUCCESS and booking CANCELLED", ready)
        self._expect_refund_log(payment_id)

    def _expect_refund_log(self, payment_id: str) -> None:
        deadline = time.monotonic() + 10
        last = ""
        while True:
            logs = _compose("logs", "worker", "--tail", "400", "--no-color")
            last = (logs.stdout or "") + (logs.stderr or "")
            for line in last.splitlines():
                if payment_id in line and "refund_required" in line and "true" in line.lower():
                    return
            if time.monotonic() >= deadline:
                raise Fail("worker log refund_required true", _clip(last[-1500:]))
            time.sleep(0.25)

    def w7(self) -> None:
        booking_id, payment_id, reference, _amount = self.pending_payment()
        payload = self._event(reference, "1.00", "payment.succeeded")
        resp = self.webhook(payload)
        self.expect_status(resp, 200)

        def ready():
            state = self.event_state(payload["event_id"])
            return True if state.get("status") == "FAILED" else state

        self.poll("mismatch event FAILED", ready)
        payment = self.request("GET", f"/payments/{payment_id}/", token=self.token_a)
        booking = self.request("GET", f"/bookings/{booking_id}/", token=self.token_a)
        self.expect(payment.data["status"] == "INITIATED", "INITIATED", payment.data["status"])  # type: ignore[index]
        self.expect(booking.data["status"] == "PENDING", "PENDING", booking.data["status"])  # type: ignore[index]

    def w8(self) -> None:
        before = self.request("GET", f"/bookings/{self._control_booking}/", token=self.token_a)
        payload = self._event("sim_pay_doesnotexist", "450.00", "payment.succeeded")
        resp = self.webhook(payload)
        self.expect_status(resp, 200)

        def ready():
            state = self.event_state(payload["event_id"])
            return True if state.get("status") == "FAILED" else state

        self.poll("unknown reference event FAILED", ready)
        after = self.request("GET", f"/bookings/{self._control_booking}/", token=self.token_a)
        history = self.request("GET", f"/bookings/{self._control_booking}/payments/", token=self.token_a)
        self.expect(after.data["status"] == before.data["status"], before.data["status"], after.data["status"])  # type: ignore[index]
        self.expect(history.data["count"] == self._control_payments, self._control_payments, history.data["count"])  # type: ignore[index]

    def w9(self) -> None:
        payload = self._event(self.p17_ref, self.p17_amount, "payment.refunded_maybe")
        resp = self.webhook(payload)
        self.expect_status(resp, 200)
        self.expect(resp.data["status"] == "ignored", "ignored", resp.data)  # type: ignore[index]
        self.expect(self.event_state(payload["event_id"])["status"] == "IGNORED", "IGNORED", "other")

    def w10(self) -> None:
        payload = self._event(self.p17_ref, self.p17_amount, "payment.succeeded")
        resp = self.webhook(payload, signature="sha256=" + ("ab" * 32))
        self.expect_error(resp, 401, "INVALID_WEBHOOK_SIGNATURE")
        self.expect(self.event_state(payload["event_id"])["count"] == 0, "no event row", "row created")

    def w11(self) -> None:
        payload = self._event(self.p17_ref, self.p17_amount, "payment.succeeded")
        resp = self.webhook(payload, include_signature=False)
        self.expect_error(resp, 401, "INVALID_WEBHOOK_SIGNATURE")
        self.expect(self.event_state(payload["event_id"])["count"] == 0, "no event row", "row created")

    def w12(self) -> None:
        payload = self._event(self.p17_ref, self.p17_amount, "payment.succeeded")
        resp = self.webhook(payload, timestamp=str(int(time.time()) - 600))
        self.expect_error(resp, 401, "INVALID_WEBHOOK_SIGNATURE")

    def w13(self) -> None:
        payload = {
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event_id": f"evt_{uuid.uuid4()}",
            "event_type": "payment.succeeded",
        }
        resp = self.webhook(payload)
        self.expect_error(resp, 400, "VALIDATION_ERROR")
        self.expect(self.event_state(payload["event_id"])["count"] == 0, "no event row", "row created")

    def w14(self) -> None:
        original = self._event(self.p17_ref, self.p17_amount, "payment.succeeded")
        tampered = dict(original)
        tampered["data"] = dict(original["data"])
        tampered["data"]["amount"] = "1.00"
        resp = self.webhook(
            tampered,
            signature=_sign(_canonical(original), self.secret),
            raw=_canonical(tampered),
        )
        self.expect_error(resp, 401, "INVALID_WEBHOOK_SIGNATURE")
        self.expect(self.event_state(original["event_id"])["count"] == 0, "no event row", "row created")

    def w15(self) -> None:
        booking_id, _payment_id, reference, amount = self.pending_payment()
        payload = self._event(reference, amount, "payment.succeeded")
        raw = _canonical(payload)
        signature = _sign(raw, self.secret)
        timestamp = str(int(time.time()))
        url = f"{self.base_url}/payments/webhook/"

        def one(_index: int) -> httpx.Response:
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature,
                "X-Webhook-Timestamp": timestamp,
            }
            with httpx.Client(timeout=30.0) as client:
                return client.post(url, content=raw, headers=headers)

        responses = self._burst(10, one)
        for raw_resp in responses:
            self.exchanges.append(_parse_response(raw_resp, "W15"))
        codes = [item.status_code for item in responses]
        self.expect(codes == [200] * 10, "10 x 200", codes)

        def ready():
            state = self.event_state(payload["event_id"])
            booking = self.request("GET", f"/bookings/{booking_id}/", token=self.token_a)
            if state.get("count") == 1 and state.get("status") == "PROCESSED":
                if isinstance(booking.data, dict) and booking.data.get("status") == "CONFIRMED":
                    return True
            return {"event": state, "booking": booking.data}

        self.poll("1 PROCESSED event and booking CONFIRMED", ready)

    def w16(self) -> None:
        resp = self.request("GET", "/payments/webhook/", retry=False)
        self.expect_error(resp, 405, "METHOD_NOT_ALLOWED")

    def section_x(self) -> None:
        self.case("X1", "Envelope audit", self.x1)
        self.case("X2", "No secrets in responses", self.x2)
        flushed = _compose("exec", "-T", "redis", "redis-cli", "FLUSHDB")
        if flushed.returncode != 0:
            message = _clip(flushed.stderr or flushed.stdout)

            def flush_failed() -> None:
                raise Fail("redis FLUSHDB", message)

            self.case("X3", "Login throttling", flush_failed)
        else:
            self.case("X3", "Login throttling", self.x3)
        self.case("X4", "Logs are structured", self.x4)

    def x1(self) -> None:
        failures = []
        for item in self.exchanges:
            if item.status >= 500:
                failures.append(f"{item.case_id} HTTP {item.status}")
            if item.status < 400:
                continue
            if "html" in item.content_type.lower() or item.text.lstrip().lower().startswith("<!doctype"):
                failures.append(f"{item.case_id} HTML {item.status}")
                continue
            body = item.data
            if not isinstance(body, dict) or not isinstance(body.get("error"), dict):
                failures.append(f"{item.case_id} missing envelope")
                continue
            err = body["error"]
            if not isinstance(err.get("code"), str) or not isinstance(err.get("message"), str):
                failures.append(f"{item.case_id} incomplete envelope")
        self.expect(not failures, "every error is a JSON envelope and there are zero 500s", failures)

    def x2(self) -> None:
        secret = self.secret
        problems = []
        for item in self.exchanges:
            if secret and secret in item.text:
                problems.append(f"{item.case_id} contains WEBHOOK_SECRET")
            lowered = item.text.lower()
            if "traceback (most recent call last)" in lowered or "pbkdf2" in lowered:
                problems.append(f"{item.case_id} contains a secret or stack trace")
            if _has_password_field(item.data):
                problems.append(f"{item.case_id} contains a password field")
        self.expect(not problems, "no password field, hash, webhook secret, or stack trace", problems)

    def x3(self) -> None:
        statuses = []
        last = None
        for _ in range(6):
            last = self.request(
                "POST",
                "/auth/login/",
                json_body={"email": self.email_a, "password": "wrong-password"},
                retry=False,
            )
            statuses.append(last.status)
        self.expect(statuses[:5] == [401, 401, 401, 401, 401], "first 5 are 401", statuses)
        self.expect_error(last, 429, "THROTTLED")

    def x4(self) -> None:
        logs = _compose("logs", "web", "--since", "30m", "--no-color")
        text = (logs.stdout or "") + "\n" + (logs.stderr or "")
        if logs.returncode != 0:
            raise Fail("docker compose logs web", _clip(text))
        json_request_ids = 0
        duplicates = 0
        for line in text.splitlines():
            start = line.find("{")
            if start < 0:
                continue
            try:
                obj = json.loads(line[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("request_id"):
                json_request_ids += 1
            if isinstance(obj, dict) and obj.get("event") == "webhook_duplicate":
                duplicates += 1
        self.expect(json_request_ids > 0, "JSON lines containing request_id", f"matches={json_request_ids}")
        self.expect(duplicates > 0, "webhook_duplicate events from W2", f"matches={duplicates}")

    def _burst(self, count: int, fn) -> list:
        barrier = threading.Barrier(count)
        results: list = [None] * count
        errors: list = []

        def run(index: int) -> None:
            try:
                barrier.wait(10)
                results[index] = fn(index)
            except Exception as exc:  # noqa: BLE001 - one thread must not kill the burst
                errors.append(repr(exc))

        threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(40)
        if errors or any(item is None for item in results):
            raise Fail("concurrent requests finished", errors or results)
        return results

    def write_report(self) -> None:
        passed = sum(1 for row in self.results if row.status == "PASS")
        failed = sum(1 for row in self.results if row.status == "FAIL")
        skipped = sum(1 for row in self.results if row.status == "SKIP")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            "# API test report",
            "",
            f"- **Timestamp:** {stamp}",
            f"- **Git commit:** `{_git_commit()}`",
            f"- **Base URL:** {self.base_url}",
            "",
            "## Summary",
            "",
            "| Total | Passed | Failed | Skipped |",
            "| --- | --- | --- | --- |",
            f"| {len(self.results)} | {passed} | {failed} | {skipped} |",
            "",
            "## Cases",
            "",
            "| ID | Result | Label | Detail |",
            "| --- | --- | --- | --- |",
        ]
        for row in self.results:
            detail = row.detail.replace("|", "/")
            lines.append(f"| {row.case_id} | {row.status} | {row.label} | {detail} |")
        if failed:
            lines.extend(["", "## Failures", ""])
            for row in self.results:
                if row.status != "FAIL":
                    continue
                lines.extend(
                    [
                        f"### {row.case_id} {row.label}",
                        "",
                        "**Expected**",
                        "",
                        "```",
                        row.expected,
                        "```",
                        "",
                        "**Actual**",
                        "",
                        "```",
                        row.actual,
                        "```",
                        "",
                    ]
                )
        skips = [row for row in self.results if row.status == "SKIP"]
        if skips:
            lines.extend(["", "## Skipped", ""])
            for row in skips:
                lines.append(f"- **{row.case_id}** {row.detail}")
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def print_summary(self) -> None:
        passed = sum(1 for row in self.results if row.status == "PASS")
        failed = sum(1 for row in self.results if row.status == "FAIL")
        skipped = sum(1 for row in self.results if row.status == "SKIP")
        print(
            f"\nSummary  total={len(self.results)}  passed={passed}  failed={failed}  skipped={skipped}",
            flush=True,
        )
        print(f"Report   {REPORT_PATH}", flush=True)


class _Bound(Exchange):
    def __init__(self, exchange: Exchange, headers: httpx.Headers):
        super().__init__(
            exchange.case_id,
            exchange.status,
            exchange.text,
            exchange.content_type,
            exchange.data,
        )
        self.headers = headers


def _clip(value: object, limit: int = 800) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _has_password_field(value: object, *, parent_key: str | None = None) -> bool:
    """True when a response body appears to leak a password or hash.

    Field names under ``error.details`` (e.g. AU4's ``details.password``) are
    validation keys, not leaked credentials.
    """
    if isinstance(value, dict):
        under_details = parent_key == "details"
        for key, item in value.items():
            key_l = str(key).lower()
            if key_l in {"password_hash", "hashed_password"}:
                return True
            if key_l == "password" and not under_details:
                return True
            if _has_password_field(item, parent_key=key_l):
                return True
    elif isinstance(value, list):
        return any(_has_password_field(item, parent_key=parent_key) for item in value)
    return False


def main() -> None:
    _enable_windows_color()
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Run the EVE Healthcare API smoke matrix.")
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    parser.add_argument(
        "--flush-throttle",
        action="store_true",
        help="FLUSHDBs Redis before the run so earlier throttle keys cannot cause 429s.",
    )
    args = parser.parse_args()
    runner = Runner(args.base_url, args.flush_throttle)
    try:
        sys.exit(runner.run())
    finally:
        runner.close()


if __name__ == "__main__":
    main()
