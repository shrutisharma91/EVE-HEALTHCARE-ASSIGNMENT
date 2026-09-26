#!/usr/bin/env python
"""Generate Postman collection + local environment from the smoke matrix."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "postman"

ENVELOPE = """
pm.test("JSON error envelope", function () {
  pm.response.to.have.jsonBody("error");
  const err = pm.response.json().error;
  pm.expect(err).to.have.property("code").that.is.a("string");
  pm.expect(err).to.have.property("message").that.is.a("string");
  pm.expect(err).to.have.property("details");
});
""".strip()

SIGN_WEBHOOK = """
const secret = pm.environment.get("webhook_secret");
const body = pm.request.body.raw;
const ts = Math.floor(Date.now() / 1000).toString();
const sig = "sha256=" + CryptoJS.HmacSHA256(body, secret).toString(CryptoJS.enc.Hex);
pm.request.headers.upsert({ key: "X-Webhook-Timestamp", value: ts });
pm.request.headers.upsert({ key: "X-Webhook-Signature", value: sig });
pm.request.headers.upsert({ key: "Content-Type", value: "application/json" });
""".strip()

INIT_SLOTS = """
const tomorrow = new Date();
tomorrow.setDate(tomorrow.getDate() + 1);
function istIso(hour, minute) {
  const y = tomorrow.getFullYear();
  const m = String(tomorrow.getMonth() + 1).padStart(2, "0");
  const d = String(tomorrow.getDate()).padStart(2, "0");
  const hh = String(hour).padStart(2, "0");
  const mm = String(minute).padStart(2, "0");
  return `${y}-${m}-${d}T${hh}:${mm}:00+05:30`;
}
if (!pm.environment.get("slot_1")) {
  pm.environment.set("slot_1", istIso(10, 0));
  pm.environment.set("slot_2", istIso(11, 0));
  pm.environment.set("slot_3", istIso(12, 0));
  pm.environment.set("slot_4", istIso(12, 20));
  pm.environment.set("slot_5", istIso(12, 40));
  pm.environment.set("slot_6", istIso(13, 0));
  pm.environment.set("slot_7", istIso(13, 20));
  pm.environment.set("slot_8", istIso(13, 40));
  pm.environment.set("slot_9", istIso(14, 0));
  pm.environment.set("slot_10", istIso(14, 20));
  pm.environment.set("slot_11", istIso(14, 40));
  pm.environment.set("slot_12", istIso(15, 0));
  pm.environment.set("run_ts", Date.now().toString());
  pm.environment.set("email_a", `user_a_${Date.now()}@test.dev`);
  pm.environment.set("email_b", `user_b_${Date.now()}@test.dev`);
  pm.environment.set("idem_p1", require("uuid").v4());
  pm.environment.set("event_w1", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w4", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w5", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w6", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w7", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w8", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w9", `evt_${require("uuid").v4()}`);
  pm.environment.set("event_w15", `evt_${require("uuid").v4()}`);
}
""".strip()

SMOKE_NOTE = (
    "Remaining checks (docker shell / Celery polling / concurrent races / log scan) "
    "are covered by `make smoke` / scripts/api_smoke_test.py."
)


def event(name: str, listen: str, exec_lines: list[str]) -> dict:
    return {
        "listen": listen,
        "script": {"type": "text/javascript", "exec": "\n".join(exec_lines).splitlines()},
    }


def req(
    case_id: str,
    label: str,
    method: str,
    path: str,
    *,
    body: str | None = None,
    auth: str | None = None,
    headers: list[tuple[str, str]] | None = None,
    tests: list[str] | None = None,
    prereq: list[str] | None = None,
    description: str | None = None,
) -> dict:
    hdrs = [{"key": k, "value": v} for k, v in (headers or [])]
    if auth:
        hdrs.append({"key": "Authorization", "value": f"Bearer {{{{{auth}}}}}"})
    item: dict = {
        "name": f"{case_id} — {label}",
        "request": {
            "method": method,
            "header": hdrs,
            "url": "{{base_url}}" + path,
        },
        "event": [],
    }
    if description:
        item["request"]["description"] = description
    if body is not None:
        item["request"]["body"] = {
            "mode": "raw",
            "raw": body,
            "options": {"raw": {"language": "json"}},
        }
        if not any(h["key"].lower() == "content-type" for h in hdrs):
            hdrs.append({"key": "Content-Type", "value": "application/json"})
    scripts: list[dict] = []
    if prereq:
        scripts.append(event("prerequest", "prerequest", prereq))
    if tests:
        scripts.append(event("test", "test", tests))
    item["event"] = scripts
    return item


def folder(name: str, items: list[dict]) -> dict:
    return {"name": name, "item": items}


def status_eq(code: int) -> str:
    return f'pm.test("status {code}", () => pm.response.to.have.status({code}));'


def code_eq(code: str) -> str:
    return f"""
pm.test("error.code {code}", function () {{
  pm.expect(pm.response.json().error.code).to.eql("{code}");
}});
""".strip()


def skip_stub(case_id: str, label: str, pytest_name: str) -> dict:
    return {
        "name": f"{case_id} — {label} (SKIP)",
        "request": {
            "method": "GET",
            "header": [],
            "url": "{{base_url}}/health/",
            "description": f"SKIP — covered by pytest: {pytest_name}",
        },
        "event": [
            event(
                "test",
                "test",
                ['pm.test("SKIP documented", () => pm.expect(true).to.be.true);'],
            )
        ],
    }


def webhook_build_and_sign(
    *,
    event_id_expr: str,
    event_type: str,
    provider_ref_expr: str,
    amount_expr: str,
    timestamp_js: str | None = None,
) -> str:
    ts = timestamp_js or "Math.floor(Date.now() / 1000).toString()"
    return f"""
const payload = {{
  event_id: {event_id_expr},
  event_type: "{event_type}",
  data: {{
    provider_reference: {provider_ref_expr},
    amount: {amount_expr},
    currency: "INR"
  }}
}};
pm.request.body.raw = JSON.stringify(payload);
const secret = pm.environment.get("webhook_secret");
const body = pm.request.body.raw;
const ts = {ts};
const sig = "sha256=" + CryptoJS.HmacSHA256(body, secret).toString(CryptoJS.enc.Hex);
pm.request.headers.upsert({{ key: "X-Webhook-Timestamp", value: ts }});
pm.request.headers.upsert({{ key: "X-Webhook-Signature", value: sig }});
pm.request.headers.upsert({{ key: "Content-Type", value: "application/json" }});
""".strip()


def main() -> None:
    items: list[dict] = []

    # ---- H ----
    h = [
        req(
            "H1",
            "Health check",
            "GET",
            "/health/",
            prereq=[INIT_SLOTS],
            tests=[
                status_eq(200),
                'const j = pm.response.json(); pm.expect(j.status).to.eql("ok"); pm.expect(j.db).to.eql("ok"); pm.expect(j.cache).to.eql("ok");',
            ],
        ),
        req(
            "H2",
            "Swagger UI loads",
            "GET",
            "/docs/",
            tests=[
                status_eq(200),
                'pm.test("HTML", () => pm.expect(pm.response.headers.get("Content-Type")).to.include("text/html"));',
            ],
        ),
        req(
            "H3",
            "OpenAPI schema",
            "GET",
            "/schema/",
            tests=[
                status_eq(200),
                'pm.test("webhook path", () => pm.expect(pm.response.text()).to.include("/payments/webhook/"));',
            ],
        ),
        req(
            "H4",
            "Request ID header",
            "GET",
            "/health/",
            headers=[("X-Request-ID", "smoke-123")],
            tests=[
                status_eq(200),
                'pm.test("echo request id", () => pm.expect(pm.response.headers.get("X-Request-ID")).to.eql("smoke-123"));',
            ],
        ),
        req(
            "H5",
            "Unknown route",
            "GET",
            "/does-not-exist/",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "H6",
            "Wrong method",
            "PUT",
            "/health/",
            tests=[status_eq(405), ENVELOPE, code_eq("METHOD_NOT_ALLOWED")],
        ),
    ]
    items.append(folder("H — Health & docs", h))

    # ---- AU ----
    signup_a = json.dumps(
        {
            "email": "{{email_a}}",
            "password": "{{password}}",
            "full_name": "User A",
            "phone": "9876543210",
        }
    )
    signup_b = json.dumps(
        {
            "email": "{{email_b}}",
            "password": "{{password}}",
            "full_name": "User B",
            "phone": "9123456780",
        }
    )
    au = [
        req(
            "AU1",
            "Signup success",
            "POST",
            "/auth/signup/",
            body=signup_a,
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.test("tokens + no password", function () {
  pm.expect(j).to.have.property("access");
  pm.expect(j).to.have.property("refresh");
  pm.expect(j).to.not.have.property("password");
  pm.environment.set("token_a", j.access);
  pm.environment.set("refresh_a", j.refresh);
});
""".strip(),
            ],
        ),
        req(
            "AU2",
            "Signup user B",
            "POST",
            "/auth/signup/",
            body=signup_b,
            tests=[
                status_eq(201),
                'const j = pm.response.json(); pm.environment.set("token_b", j.access); pm.environment.set("refresh_b", j.refresh);',
            ],
        ),
        req(
            "AU3",
            "Duplicate email, different case",
            "POST",
            "/auth/signup/",
            body=json.dumps(
                {
                    "email": "{{email_a}}",
                    "password": "{{password}}",
                    "full_name": "Dup",
                    "phone": "9876543211",
                }
            ),
            prereq=[
                'const body = JSON.parse(pm.request.body.raw); body.email = pm.environment.get("email_a").toUpperCase(); pm.request.body.raw = JSON.stringify(body);'
            ],
            tests=[status_eq(409), ENVELOPE, code_eq("EMAIL_ALREADY_REGISTERED")],
        ),
        req(
            "AU4",
            "Weak password",
            "POST",
            "/auth/signup/",
            body=json.dumps(
                {
                    "email": "weak_{{run_ts}}@test.dev",
                    "password": "123",
                    "full_name": "Weak",
                    "phone": "9876543212",
                }
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("password");',
            ],
        ),
        req(
            "AU5",
            "Missing email",
            "POST",
            "/auth/signup/",
            body=json.dumps(
                {"password": "{{password}}", "full_name": "X", "phone": "9876543213"}
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("email");',
            ],
        ),
        req(
            "AU6",
            "Invalid email format",
            "POST",
            "/auth/signup/",
            body=json.dumps(
                {
                    "email": "not-an-email",
                    "password": "{{password}}",
                    "full_name": "X",
                    "phone": "9876543214",
                }
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("email");',
            ],
        ),
        req(
            "AU7",
            "Invalid phone",
            "POST",
            "/auth/signup/",
            body=json.dumps(
                {
                    "email": "phone_{{run_ts}}@test.dev",
                    "password": "{{password}}",
                    "full_name": "X",
                    "phone": "12345",
                }
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("phone");',
            ],
        ),
        req(
            "AU8",
            "Empty body",
            "POST",
            "/auth/signup/",
            body="{}",
            tests=[status_eq(400), ENVELOPE, code_eq("VALIDATION_ERROR")],
        ),
        req(
            "AU9",
            "Malformed JSON",
            "POST",
            "/auth/signup/",
            body='{"email":',
            tests=[status_eq(400), ENVELOPE, code_eq("PARSE_ERROR")],
        ),
        req(
            "AU10",
            "Login success",
            "POST",
            "/auth/login/",
            body=json.dumps({"email": "{{email_a}}", "password": "{{password}}"}),
            tests=[
                status_eq(200),
                """
const j = pm.response.json();
pm.expect(j.access).to.be.a("string");
pm.expect(j.refresh).to.be.a("string");
pm.environment.set("token_a", j.access);
pm.environment.set("refresh_a", j.refresh);
""".strip(),
            ],
        ),
        req(
            "AU11",
            "Wrong password",
            "POST",
            "/auth/login/",
            body=json.dumps({"email": "{{email_a}}", "password": "WrongPass#1"}),
            tests=[
                status_eq(401),
                ENVELOPE,
                code_eq("INVALID_CREDENTIALS"),
                'pm.environment.set("login_fail_message", pm.response.json().error.message);',
            ],
        ),
        req(
            "AU12",
            "Unknown email",
            "POST",
            "/auth/login/",
            body=json.dumps(
                {"email": "nobody_{{run_ts}}@test.dev", "password": "{{password}}"}
            ),
            tests=[
                status_eq(401),
                ENVELOPE,
                code_eq("INVALID_CREDENTIALS"),
                'pm.test("same message as AU11", () => pm.expect(pm.response.json().error.message).to.eql(pm.environment.get("login_fail_message")));',
            ],
        ),
        req(
            "AU13",
            "Me with token",
            "GET",
            "/auth/me/",
            auth="token_a",
            tests=[
                status_eq(200),
                'const j = pm.response.json(); pm.expect(j.email).to.eql(pm.environment.get("email_a")); pm.expect(j).to.not.have.property("password");',
            ],
        ),
        req(
            "AU14",
            "Me without token",
            "GET",
            "/auth/me/",
            tests=[status_eq(401), ENVELOPE, code_eq("NOT_AUTHENTICATED")],
        ),
        req(
            "AU15",
            "Me with garbage token",
            "GET",
            "/auth/me/",
            headers=[("Authorization", "Bearer abc.def.ghi")],
            tests=[status_eq(401), ENVELOPE, code_eq("AUTHENTICATION_FAILED")],
        ),
        req(
            "AU16",
            "Refresh token",
            "POST",
            "/auth/token/refresh/",
            body=json.dumps({"refresh": "{{refresh_a}}"}),
            tests=[
                status_eq(200),
                """
const j = pm.response.json();
pm.expect(j.access).to.be.a("string");
pm.environment.set("old_refresh_a", pm.environment.get("refresh_a"));
pm.environment.set("token_a", j.access);
if (j.refresh) { pm.environment.set("refresh_a", j.refresh); }
""".strip(),
            ],
        ),
        req(
            "AU17",
            "Reuse rotated refresh",
            "POST",
            "/auth/token/refresh/",
            body=json.dumps({"refresh": "{{old_refresh_a}}"}),
            tests=[status_eq(401), ENVELOPE, code_eq("AUTHENTICATION_FAILED")],
        ),
        skip_stub(
            "AU18",
            "Expired access token",
            "tests/accounts/test_auth.py::test_expired_access_token_is_rejected",
        ),
        req(
            "AU-admin",
            "Login seeded admin",
            "POST",
            "/auth/login/",
            body=json.dumps({"email": "{{admin_email}}", "password": "{{admin_password}}"}),
            tests=[
                status_eq(200),
                'pm.environment.set("token_admin", pm.response.json().access);',
            ],
        ),
    ]
    items.append(folder("AU — Authentication", au))

    # ---- C ----
    c = [
        req(
            "C1",
            "List centres",
            "GET",
            "/centres/",
            tests=[
                status_eq(200),
                """
const j = pm.response.json();
pm.expect(j).to.include.keys("count", "next", "previous", "results");
pm.expect(j.count).to.be.at.least(5);
const g = j.results.find(r => r.city === "Guwahati") || j.results[0];
pm.environment.set("cid", g.id);
""".strip(),
            ],
        ),
        req(
            "C2",
            "Filter by city",
            "GET",
            "/centres/?city=Guwahati&page_size=100",
            tests=[
                status_eq(200),
                """
const rows = pm.response.json().results;
pm.expect(rows.length).to.be.above(0);
rows.forEach(r => pm.expect(r.city).to.eql("Guwahati"));
const match = rows.find(r => r.name === "EVE Diagnostics Guwahati") || rows[0];
pm.environment.set("cid", match.id);
""".strip(),
            ],
        ),
        req(
            "C3",
            "Filter by test",
            "GET",
            "/centres/?test_code=CBC&page_size=100",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().results.length).to.be.above(0);',
            ],
            description=(
                "Asserts filtered list is non-empty. Per-centre CBC offering checks "
                f"via follow-up GETs are covered by `make smoke`. {SMOKE_NOTE}"
            ),
        ),
        req(
            "C4",
            "Search by name",
            "GET",
            "/centres/?search=Guwahati&page_size=100",
            tests=[
                status_eq(200),
                'pm.response.json().results.forEach(r => pm.expect(r.name.toLowerCase()).to.include("guwahati"));',
            ],
        ),
        req(
            "C5",
            "Page size",
            "GET",
            "/centres/?page_size=2",
            tests=[
                status_eq(200),
                'const j = pm.response.json(); pm.expect(j.results.length).to.eql(2); pm.expect(j.next).to.not.be.null;',
            ],
        ),
        req(
            "C6",
            "Oversized page size",
            "GET",
            "/centres/?page_size=10000",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().results.length).to.be.at.most(100);',
            ],
        ),
        req(
            "C7",
            "Page out of range",
            "GET",
            "/centres/?page=9999",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "C8",
            "Centre detail",
            "GET",
            "/centres/{{cid}}/",
            tests=[
                status_eq(200),
                """
const j = pm.response.json();
const offering = (j.tests || []).find(t => t.code === "CBC") || (j.tests || [])[0];
pm.expect(offering).to.exist;
pm.expect(offering).to.have.property("id");
pm.expect(offering).to.have.property("code");
pm.expect(offering).to.have.property("price");
pm.environment.set("tid", offering.id);
pm.environment.set("price", String(offering.price));
""".strip(),
            ],
            description="Centre detail returns tests[] with id = DiagnosticTest id, code, price.",
        ),
        req(
            "C9",
            "Centre not found",
            "GET",
            "/centres/00000000-0000-4000-8000-000000000099/",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "C10",
            "Centre tests",
            "GET",
            "/centres/{{cid}}/tests/",
            tests=[
                status_eq(200),
                """
const rows = pm.response.json();
const list = Array.isArray(rows) ? rows : (rows.results || []);
pm.expect(list.length).to.be.above(0);
list.forEach(t => { pm.expect(t).to.have.property("code"); pm.expect(t).to.have.property("price"); });
""".strip(),
            ],
        ),
        req(
            "C11",
            "Test catalogue",
            "GET",
            "/tests/?search=thyroid",
            tests=[
                status_eq(200),
                'const names = (pm.response.json().results || pm.response.json()).map(t => t.name).join(" "); pm.expect(names.toLowerCase()).to.include("thyroid");',
            ],
        ),
        req(
            "C11-catalogue",
            "Load LFT/KFT/XRAY/URINE IDs",
            "GET",
            "/tests/?page_size=100",
            tests=[
                status_eq(200),
                """
const rows = pm.response.json().results || pm.response.json();
const byCode = {};
rows.forEach(t => { byCode[t.code] = t.id; });
pm.expect(byCode.LFT).to.exist;
pm.expect(byCode.KFT).to.exist;
pm.expect(byCode.XRAY_CHEST).to.exist;
pm.expect(byCode.URINE).to.exist;
pm.environment.set("tid_lft", byCode.LFT);
pm.environment.set("tid_kft", byCode.KFT);
pm.environment.set("tid_xray", byCode.XRAY_CHEST);
pm.environment.set("tid_urine", byCode.URINE);
if (byCode.CBC) { pm.environment.set("tid_cbc", byCode.CBC); }
""".strip(),
            ],
            description="C18 uses different test IDs (LFT/KFT). Also loads XRAY_CHEST and URINE for B6/B7.",
        ),
        req(
            "C12",
            "Anonymous create",
            "POST",
            "/centres/",
            body=json.dumps(
                {
                    "name": "Anon",
                    "address": "x",
                    "city": "Guwahati",
                    "pincode": "781001",
                    "phone": "9876543210",
                }
            ),
            tests=[status_eq(401), ENVELOPE, code_eq("NOT_AUTHENTICATED")],
        ),
        req(
            "C13",
            "Non-admin create",
            "POST",
            "/centres/",
            auth="token_a",
            body=json.dumps(
                {
                    "name": "Patient Lab",
                    "address": "x",
                    "city": "Guwahati",
                    "pincode": "781001",
                    "phone": "9876543210",
                }
            ),
            tests=[status_eq(403), ENVELOPE, code_eq("PERMISSION_DENIED")],
        ),
        req(
            "C14",
            "Admin create centre",
            "POST",
            "/centres/",
            auth="token_admin",
            body=json.dumps(
                {
                    "name": "Smoke Lab {{run_ts}}",
                    "address": "1 Test Street",
                    "city": "Guwahati",
                    "pincode": "781001",
                    "phone": "9876500001",
                }
            ),
            tests=[
                status_eq(201),
                """
pm.environment.set("new_centre", pm.response.json().id);
pm.environment.set("new_centre_name", "Smoke Lab " + pm.environment.get("run_ts"));
""".strip(),
            ],
        ),
        req(
            "C15",
            "Duplicate name + city",
            "POST",
            "/centres/",
            auth="token_admin",
            body=json.dumps(
                {
                    "name": "Smoke Lab {{run_ts}}",
                    "address": "1 Test Street",
                    "city": "Guwahati",
                    "pincode": "781001",
                    "phone": "9876500001",
                }
            ),
            tests=[status_eq(409), ENVELOPE, code_eq("CENTRE_ALREADY_EXISTS")],
        ),
        req(
            "C16",
            "Invalid pincode",
            "POST",
            "/centres/",
            auth="token_admin",
            body=json.dumps(
                {
                    "name": "Bad Pin {{run_ts}}",
                    "address": "x",
                    "city": "Guwahati",
                    "pincode": "12",
                    "phone": "9876500002",
                }
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("pincode");',
            ],
        ),
        req(
            "C17",
            "Add test to centre",
            "POST",
            "/centres/{{new_centre}}/tests/",
            auth="token_admin",
            body=json.dumps({"test_id": "{{tid}}", "price": "450.00"}),
            tests=[
                status_eq(201),
                'pm.environment.set("added_test", pm.environment.get("tid"));',
            ],
        ),
        req(
            "C18a",
            "Zero price (LFT)",
            "POST",
            "/centres/{{new_centre}}/tests/",
            auth="token_admin",
            body=json.dumps({"test_id": "{{tid_lft}}", "price": "0"}),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("price");',
            ],
        ),
        req(
            "C18b",
            "Negative price (KFT)",
            "POST",
            "/centres/{{new_centre}}/tests/",
            auth="token_admin",
            body=json.dumps({"test_id": "{{tid_kft}}", "price": "-10"}),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("price");',
            ],
        ),
        req(
            "C19",
            "Same test twice",
            "POST",
            "/centres/{{new_centre}}/tests/",
            auth="token_admin",
            body=json.dumps({"test_id": "{{tid}}", "price": "450.00"}),
            tests=[status_eq(409), ENVELOPE, code_eq("TEST_ALREADY_OFFERED")],
        ),
        req(
            "C20-patch",
            "Update price",
            "PATCH",
            "/centres/{{new_centre}}/tests/{{tid}}/",
            auth="token_admin",
            body=json.dumps({"price": "500.00"}),
            tests=[status_eq(200)],
            description="PATCH centre test URL is /centres/{centre_id}/tests/{test_id}/",
        ),
        req(
            "C20-get",
            "Cache invalidated",
            "GET",
            "/centres/{{new_centre}}/",
            tests=[
                status_eq(200),
                """
const row = pm.response.json().tests.find(t => t.id === pm.environment.get("tid"));
pm.expect(String(row.price)).to.eql("500.00");
""".strip(),
            ],
        ),
        req(
            "C21-delete",
            "Soft delete",
            "DELETE",
            "/centres/{{new_centre}}/",
            auth="token_admin",
            tests=[
                status_eq(204),
                'pm.environment.set("deleted_centre", pm.environment.get("new_centre"));',
            ],
            description="Soft-deleted centre from C21 is reused for B8.",
        ),
        req(
            "C21-list",
            "Soft-deleted absent from list",
            "GET",
            "/centres/?search={{new_centre_name}}&page_size=100",
            tests=[
                status_eq(200),
                """
const ids = pm.response.json().results.map(r => r.id);
pm.expect(ids).to.not.include(pm.environment.get("deleted_centre"));
""".strip(),
            ],
        ),
        req(
            "C21-detail",
            "Soft-deleted public detail 404",
            "GET",
            "/centres/{{deleted_centre}}/",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
    ]
    items.append(folder("C — Catalog", c))

    # ---- B ----
    book_body = json.dumps(
        {
            "centre_id": "{{cid}}",
            "test_id": "{{tid}}",
            "appointment_at": "{{slot_1}}",
        }
    )
    b = [
        req(
            "B1",
            "Create booking",
            "POST",
            "/bookings/",
            auth="token_a",
            body=book_body,
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.expect(j.status).to.eql("PENDING");
pm.expect(String(j.amount)).to.eql(pm.environment.get("price"));
pm.environment.set("b1", j.id);
pm.environment.set("b1_amount", String(j.amount));
""".strip(),
            ],
        ),
        req(
            "B2",
            "Client amount ignored",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_2}}",
                    "amount": "1.00",
                }
            ),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.expect(String(j.amount)).to.not.eql("1.00");
pm.expect(String(j.amount)).to.eql(pm.environment.get("price"));
pm.environment.set("b2", j.id);
""".strip(),
            ],
        ),
        req(
            "B3",
            "Past appointment",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "2020-01-01T10:00:00+05:30",
                }
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("appointment_at");',
            ],
        ),
        req(
            "B4",
            "Beyond 90 days",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_1}}",
                }
            ),
            prereq=[
                """
const d = new Date();
d.setDate(d.getDate() + 120);
const y = d.getFullYear();
const m = String(d.getMonth() + 1).padStart(2, "0");
const day = String(d.getDate()).padStart(2, "0");
const body = JSON.parse(pm.request.body.raw);
body.appointment_at = `${y}-${m}-${day}T10:00:00+05:30`;
pm.request.body.raw = JSON.stringify(body);
""".strip()
            ],
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("appointment_at");',
            ],
        ),
        req(
            "B5",
            "Outside operating hours",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_1}}",
                }
            ),
            prereq=[
                """
const tomorrow = new Date();
tomorrow.setDate(tomorrow.getDate() + 1);
const y = tomorrow.getFullYear();
const m = String(tomorrow.getMonth() + 1).padStart(2, "0");
const d = String(tomorrow.getDate()).padStart(2, "0");
const body = JSON.parse(pm.request.body.raw);
body.appointment_at = `${y}-${m}-${d}T22:00:00+05:30`;
pm.request.body.raw = JSON.stringify(body);
""".strip()
            ],
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("appointment_at");',
            ],
        ),
        req(
            "B6",
            "Test not offered at centre",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid_xray}}",
                    "appointment_at": "{{slot_3}}",
                }
            ),
            tests=[status_eq(400), ENVELOPE, code_eq("TEST_NOT_OFFERED_AT_CENTRE")],
        ),
        req(
            "B7-off",
            "Mark URINE unavailable",
            "PATCH",
            "/centres/{{cid}}/tests/{{tid_urine}}/",
            auth="token_admin",
            body=json.dumps({"is_available": False}),
            tests=[status_eq(200)],
        ),
        req(
            "B7-book",
            "Test unavailable at centre",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid_urine}}",
                    "appointment_at": "{{slot_3}}",
                }
            ),
            tests=[status_eq(400), ENVELOPE, code_eq("TEST_UNAVAILABLE")],
        ),
        req(
            "B7-restore",
            "Restore URINE available",
            "PATCH",
            "/centres/{{cid}}/tests/{{tid_urine}}/",
            auth="token_admin",
            body=json.dumps({"is_available": True}),
            tests=[status_eq(200)],
        ),
        req(
            "B8",
            "Inactive centre",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{deleted_centre}}",
                    "test_id": "{{added_test}}",
                    "appointment_at": "{{slot_3}}",
                }
            ),
            tests=[status_eq(400), ENVELOPE, code_eq("CENTRE_INACTIVE")],
            description="Uses soft-deleted centre from C21.",
        ),
        req(
            "B9",
            "Nonexistent centre",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "00000000-0000-4000-8000-000000000098",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_3}}",
                }
            ),
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "B10",
            "Missing fields",
            "POST",
            "/bookings/",
            auth="token_a",
            body="{}",
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                """
const d = pm.response.json().error.details;
pm.expect(d).to.have.property("centre_id");
pm.expect(d).to.have.property("test_id");
pm.expect(d).to.have.property("appointment_at");
""".strip(),
            ],
        ),
        req(
            "B11",
            "Bad datetime",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "tomorrow",
                }
            ),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("appointment_at");',
            ],
        ),
        req(
            "B12",
            "Duplicate active booking",
            "POST",
            "/bookings/",
            auth="token_a",
            body=book_body,
            tests=[status_eq(409), ENVELOPE, code_eq("DUPLICATE_BOOKING")],
        ),
        req(
            "B13",
            "No token",
            "POST",
            "/bookings/",
            body=book_body,
            tests=[status_eq(401), ENVELOPE, code_eq("NOT_AUTHENTICATED")],
        ),
        req(
            "B14",
            "List own only",
            "GET",
            "/bookings/",
            auth="token_b",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().count).to.eql(0);',
            ],
        ),
        req(
            "B15",
            "Filter by status",
            "GET",
            "/bookings/?status=PENDING",
            auth="token_a",
            tests=[
                status_eq(200),
                """
const rows = pm.response.json().results;
pm.expect(rows.length).to.be.above(0);
rows.forEach(r => pm.expect(r.status).to.eql("PENDING"));
""".strip(),
            ],
        ),
        req(
            "B16",
            "Get own booking",
            "GET",
            "/bookings/{{b1}}/",
            auth="token_a",
            tests=[status_eq(200)],
        ),
        req(
            "B17",
            "Get other's booking",
            "GET",
            "/bookings/{{b1}}/",
            auth="token_b",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "B18",
            "Malformed UUID",
            "GET",
            "/bookings/not-a-uuid/",
            auth="token_a",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "B19",
            "Cancel pending",
            "POST",
            "/bookings/{{b2}}/cancel/",
            auth="token_a",
            body=json.dumps({"reason": "test"}),
            tests=[
                status_eq(200),
                'const j = pm.response.json(); pm.expect(j.status).to.eql("CANCELLED"); pm.expect(j.cancelled_at).to.exist;',
            ],
        ),
        req(
            "B20",
            "Cancel again",
            "POST",
            "/bookings/{{b2}}/cancel/",
            auth="token_a",
            body=json.dumps({"reason": "test"}),
            tests=[status_eq(409), ENVELOPE, code_eq("INVALID_STATE_TRANSITION")],
        ),
        req(
            "B21",
            "Cancel other's booking",
            "POST",
            "/bookings/{{b1}}/cancel/",
            auth="token_b",
            body=json.dumps({"reason": "test"}),
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "B22",
            "Rebook cancelled slot",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_2}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b2_rebook", pm.response.json().id);',
            ],
        ),
        req(
            "B23-patch",
            "Price snapshot — change catalogue price",
            "PATCH",
            "/centres/{{cid}}/tests/{{tid}}/",
            auth="token_admin",
            body=json.dumps({"price": "510.00"}),
            tests=[status_eq(200)],
        ),
        req(
            "B23-get",
            "Price snapshot — booking amount unchanged",
            "GET",
            "/bookings/{{b1}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(String(pm.response.json().amount)).to.eql(pm.environment.get("price"));',
            ],
        ),
        req(
            "B23-restore",
            "Price snapshot — restore catalogue price",
            "PATCH",
            "/centres/{{cid}}/tests/{{tid}}/",
            auth="token_admin",
            body=json.dumps({"price": "{{price}}"}),
            tests=[status_eq(200)],
        ),
        skip_stub(
            "B25",
            "Cancel confirmed < 2h",
            "tests/bookings/test_bookings.py::test_cancel_follows_the_state_machine",
        ),
    ]
    items.append(folder("B — Bookings", b))

    # ---- P ----
    p = [
        req(
            "P1",
            "Success",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{idem_p1}}")],
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "SUCCESS"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.expect(j.status).to.eql("SUCCESS");
pm.expect(String(j.amount)).to.eql(pm.environment.get("b1_amount"));
pm.expect(j.booking_status).to.eql("CONFIRMED");
pm.environment.set("p1", j.id);
""".strip(),
            ],
        ),
        req(
            "P2-book",
            "Booking for failure payment",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_3}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b3", pm.response.json().id);',
            ],
        ),
        req(
            "P2",
            "Failure",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b3}}", "simulate_outcome": "FAILED"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.expect(j.status).to.eql("FAILED");
pm.expect(j.failure_reason).to.exist;
pm.expect(j.booking_status).to.eql("FAILED");
pm.environment.set("p2", j.id);
""".strip(),
            ],
        ),
        req(
            "P3",
            "Missing Idempotency-Key",
            "POST",
            "/payments/",
            auth="token_a",
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(400), ENVELOPE, code_eq("IDEMPOTENCY_KEY_REQUIRED")],
        ),
        req(
            "P4",
            "Idempotent replay",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{idem_p1}}")],
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "SUCCESS"}),
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().id).to.eql(pm.environment.get("p1"));',
            ],
        ),
        req(
            "P4-history",
            "Booking payment history after replay",
            "GET",
            "/bookings/{{b1}}/payments/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().count).to.eql(1);',
            ],
        ),
        req(
            "P5-book",
            "Booking for idempotency reuse",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_4}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b4", pm.response.json().id);',
            ],
        ),
        req(
            "P5",
            "Key reused, different booking",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{idem_p1}}")],
            body=json.dumps({"booking_id": "{{b4}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(422), ENVELOPE, code_eq("IDEMPOTENCY_KEY_REUSED")],
        ),
        req(
            "P6",
            "Pay confirmed booking",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(409), ENVELOPE, code_eq("BOOKING_ALREADY_PAID")],
        ),
        req(
            "B24",
            "Cancel confirmed > 2h away",
            "POST",
            "/bookings/{{b1}}/cancel/",
            auth="token_a",
            body=json.dumps({"reason": "smoke"}),
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CANCELLED");',
            ],
            description="Runs after P6 so {b1} is still CONFIRMED when P6 executes.",
        ),
        req(
            "P7",
            "Pay failed booking",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b3}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(409), ENVELOPE, code_eq("BOOKING_NOT_PAYABLE")],
        ),
        req(
            "P8",
            "Pay cancelled booking",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b2}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(409), ENVELOPE, code_eq("BOOKING_NOT_PAYABLE")],
        ),
        req(
            "P9",
            "Pay other's booking",
            "POST",
            "/payments/",
            auth="token_b",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "P10",
            "Nonexistent booking",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps(
                {
                    "booking_id": "00000000-0000-4000-8000-000000000097",
                    "simulate_outcome": "SUCCESS",
                }
            ),
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "P11",
            "Malformed booking_id",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "abc", "simulate_outcome": "SUCCESS"}),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("booking_id");',
            ],
        ),
        req(
            "P12",
            "Invalid outcome",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "MAYBE"}),
            tests=[
                status_eq(400),
                ENVELOPE,
                code_eq("VALIDATION_ERROR"),
                'pm.expect(pm.response.json().error.details).to.have.property("simulate_outcome");',
            ],
        ),
        req(
            "P13-book",
            "Booking for client amount ignored",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_6}}",
                }
            ),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.environment.set("b13", j.id);
pm.environment.set("b13_amount", String(j.amount));
""".strip(),
            ],
        ),
        req(
            "P13",
            "Client amount ignored",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps(
                {
                    "booking_id": "{{b13}}",
                    "simulate_outcome": "SUCCESS",
                    "amount": "1.00",
                }
            ),
            tests=[
                status_eq(201),
                'pm.expect(String(pm.response.json().amount)).to.eql(pm.environment.get("b13_amount"));',
            ],
        ),
        req(
            "P14",
            "No token",
            "POST",
            "/payments/",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b1}}", "simulate_outcome": "SUCCESS"}),
            tests=[status_eq(401), ENVELOPE, code_eq("NOT_AUTHENTICATED")],
        ),
        req(
            "P15",
            "Get own payment",
            "GET",
            "/payments/{{p1}}/",
            auth="token_a",
            tests=[status_eq(200)],
        ),
        req(
            "P15b",
            "Get other's payment",
            "GET",
            "/payments/{{p1}}/",
            auth="token_b",
            tests=[status_eq(404), ENVELOPE, code_eq("NOT_FOUND")],
        ),
        req(
            "P16",
            "Booking payment history",
            "GET",
            "/bookings/{{b3}}/payments/",
            auth="token_a",
            tests=[
                status_eq(200),
                """
const j = pm.response.json();
pm.expect(j.count).to.eql(1);
pm.expect(j.results[0].status).to.eql("FAILED");
""".strip(),
            ],
        ),
        req(
            "P17-book",
            "Booking for pending payment",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_5}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b5", pm.response.json().id);',
            ],
        ),
        req(
            "P17",
            "Pending outcome",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b5}}", "simulate_outcome": "PENDING"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.expect(j.status).to.eql("INITIATED");
pm.environment.set("p17", j.id);
pm.environment.set("p17_ref", j.provider_reference);
pm.environment.set("p17_amount", String(j.amount));
""".strip(),
            ],
        ),
        req(
            "P17-booking-status",
            "Pending booking stays PENDING",
            "GET",
            "/bookings/{{b5}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("PENDING");',
            ],
        ),
        req(
            "P18-book",
            "Booking for parallel race",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_7}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b6", pm.response.json().id);',
            ],
            description=(
                "P18 race: Postman runs one SUCCESS payment here. "
                f"Five concurrent requests + exactly-one-SUCCESS assertion: {SMOKE_NOTE}"
            ),
        ),
        req(
            "P18",
            "Race representative SUCCESS payment",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b6}}", "simulate_outcome": "SUCCESS"}),
            tests=[
                status_eq(201),
                'pm.expect(pm.response.json().status).to.eql("SUCCESS");',
            ],
            description=(
                "HTTP portion of P18 (one SUCCESS). Concurrent race matrix: "
                f"{SMOKE_NOTE}"
            ),
        ),
        skip_stub(
            "P19",
            "Pay expired booking",
            "tests/payments/test_payments.py::test_expired_booking_cannot_be_paid",
        ),
    ]
    items.append(folder("P — Simulated payments", p))

    # ---- W ----
    w1_body = json.dumps(
        {
            "event_id": "{{event_w1}}",
            "event_type": "payment.succeeded",
            "data": {
                "provider_reference": "{{p17_ref}}",
                "amount": "{{p17_amount}}",
                "currency": "INR",
            },
        },
        indent=2,
    )
    w1_sign = webhook_build_and_sign(
        event_id_expr='pm.environment.get("event_w1")',
        event_type="payment.succeeded",
        provider_ref_expr='pm.environment.get("p17_ref")',
        amount_expr='pm.environment.get("p17_amount")',
    )
    w = [
        req(
            "W1",
            "Success settles payment",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[w1_sign],
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("accepted");',
            ],
            description=(
                "WebhookEvent PROCESSED row check via docker shell: "
                f"{SMOKE_NOTE}"
            ),
        ),
        req(
            "W1-poll-payment",
            "Poll payment SUCCESS",
            "GET",
            "/payments/{{p17}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("SUCCESS");',
            ],
            description="Re-run until Celery settles if needed. Full poll loop: make smoke.",
        ),
        req(
            "W1-poll-booking",
            "Poll booking CONFIRMED",
            "GET",
            "/bookings/{{b5}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                """
pm.expect(pm.response.json().status).to.eql("CONFIRMED");
pm.environment.set("control_booking", pm.environment.get("b5"));
""".strip(),
            ],
        ),
        req(
            "W1-control-payments",
            "Record control payment count",
            "GET",
            "/bookings/{{b5}}/payments/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.environment.set("control_payments", String(pm.response.json().count));',
            ],
        ),
        req(
            "W2a",
            "Duplicate delivery 1/3",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[w1_sign],
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("duplicate");',
            ],
            description=f"WebhookEvent single-row check: {SMOKE_NOTE}",
        ),
        req(
            "W2b",
            "Duplicate delivery 2/3",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[w1_sign],
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("duplicate");',
            ],
        ),
        req(
            "W2c",
            "Duplicate delivery 3/3",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[w1_sign],
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("duplicate");',
            ],
        ),
        req(
            "W2-booking",
            "Still CONFIRMED after duplicates",
            "GET",
            "/bookings/{{b5}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CONFIRMED");',
            ],
        ),
        req(
            "W2-payments",
            "Still one SUCCESS payment",
            "GET",
            "/bookings/{{b5}}/payments/",
            auth="token_a",
            tests=[
                status_eq(200),
                """
const successes = pm.response.json().results.filter(r => r.status === "SUCCESS");
pm.expect(successes.length).to.eql(1);
""".strip(),
            ],
        ),
        req(
            "W3",
            "Same event_id, different payload",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w1")',
                    event_type="payment.failed",
                    provider_ref_expr='pm.environment.get("p17_ref")',
                    amount_expr='pm.environment.get("p17_amount")',
                )
            ],
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("duplicate");',
            ],
            description=f"Still 1 WebhookEvent row: {SMOKE_NOTE}",
        ),
        req(
            "W3-payment",
            "Payment stays SUCCESS",
            "GET",
            "/payments/{{p17}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("SUCCESS");',
            ],
        ),
        req(
            "W3-booking",
            "Booking stays CONFIRMED",
            "GET",
            "/bookings/{{b5}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CONFIRMED");',
            ],
        ),
        req(
            "W4-book",
            "Booking for failure webhook",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_8}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b_w4", pm.response.json().id);',
            ],
        ),
        req(
            "W4-pay",
            "Pending payment for failure webhook",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b_w4}}", "simulate_outcome": "PENDING"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.environment.set("p_w4", j.id);
pm.environment.set("p_w4_ref", j.provider_reference);
pm.environment.set("p_w4_amount", String(j.amount));
""".strip(),
            ],
        ),
        req(
            "W4",
            "Failure settles payment",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w4")',
                    event_type="payment.failed",
                    provider_ref_expr='pm.environment.get("p_w4_ref")',
                    amount_expr='pm.environment.get("p_w4_amount")',
                )
            ],
            tests=[status_eq(200)],
            description=f"Event PROCESSED via docker shell: {SMOKE_NOTE}",
        ),
        req(
            "W4-poll-payment",
            "Poll payment FAILED",
            "GET",
            "/payments/{{p_w4}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("FAILED");',
            ],
        ),
        req(
            "W4-poll-booking",
            "Poll booking FAILED",
            "GET",
            "/bookings/{{b_w4}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("FAILED");',
            ],
        ),
        req(
            "W5",
            "Late failure after success",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w5")',
                    event_type="payment.failed",
                    provider_ref_expr='pm.environment.get("p17_ref")',
                    amount_expr='pm.environment.get("p17_amount")',
                )
            ],
            tests=[status_eq(200)],
            description=f"Wait for event PROCESSED then assert states. Full poll: {SMOKE_NOTE}",
        ),
        req(
            "W5-payment",
            "Payment still SUCCESS after late failure",
            "GET",
            "/payments/{{p17}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("SUCCESS");',
            ],
        ),
        req(
            "W5-booking",
            "Booking still CONFIRMED after late failure",
            "GET",
            "/bookings/{{b5}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CONFIRMED");',
            ],
        ),
        req(
            "W6-book",
            "Booking for success-after-cancel",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_9}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b_w6", pm.response.json().id);',
            ],
        ),
        req(
            "W6-pay",
            "Pending payment before cancel",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b_w6}}", "simulate_outcome": "PENDING"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.environment.set("p_w6", j.id);
pm.environment.set("p_w6_ref", j.provider_reference);
pm.environment.set("p_w6_amount", String(j.amount));
""".strip(),
            ],
        ),
        req(
            "W6-cancel",
            "Cancel before webhook success",
            "POST",
            "/bookings/{{b_w6}}/cancel/",
            auth="token_a",
            body=json.dumps({"reason": "before webhook"}),
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CANCELLED");',
            ],
        ),
        req(
            "W6",
            "Success after cancel",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w6")',
                    event_type="payment.succeeded",
                    provider_ref_expr='pm.environment.get("p_w6_ref")',
                    amount_expr='pm.environment.get("p_w6_amount")',
                )
            ],
            tests=[status_eq(200)],
            description=(
                "Worker log refund_required check for this payment: "
                f"{SMOKE_NOTE}"
            ),
        ),
        req(
            "W6-poll-payment",
            "Payment SUCCESS after cancel webhook",
            "GET",
            "/payments/{{p_w6}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("SUCCESS");',
            ],
        ),
        req(
            "W6-poll-booking",
            "Booking stays CANCELLED",
            "GET",
            "/bookings/{{b_w6}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CANCELLED");',
            ],
        ),
        req(
            "W7-book",
            "Booking for amount mismatch",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_10}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b_w7", pm.response.json().id);',
            ],
        ),
        req(
            "W7-pay",
            "Pending payment for amount mismatch",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b_w7}}", "simulate_outcome": "PENDING"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.environment.set("p_w7", j.id);
pm.environment.set("p_w7_ref", j.provider_reference);
""".strip(),
            ],
        ),
        req(
            "W7",
            "Amount mismatch",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w7")',
                    event_type="payment.succeeded",
                    provider_ref_expr='pm.environment.get("p_w7_ref")',
                    amount_expr='"1.00"',
                )
            ],
            tests=[status_eq(200)],
            description=f"Event FAILED via docker shell: {SMOKE_NOTE}",
        ),
        req(
            "W7-payment",
            "Payment stays INITIATED",
            "GET",
            "/payments/{{p_w7}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("INITIATED");',
            ],
        ),
        req(
            "W7-booking",
            "Booking stays PENDING",
            "GET",
            "/bookings/{{b_w7}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("PENDING");',
            ],
        ),
        req(
            "W8",
            "Unknown provider_reference",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w8")',
                    event_type="payment.succeeded",
                    provider_ref_expr='"sim_pay_doesnotexist"',
                    amount_expr='"450.00"',
                )
            ],
            tests=[status_eq(200)],
            description=f"Event FAILED via docker shell: {SMOKE_NOTE}",
        ),
        req(
            "W8-control-booking",
            "Control booking unchanged",
            "GET",
            "/bookings/{{control_booking}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CONFIRMED");',
            ],
        ),
        req(
            "W8-control-payments",
            "Control payment count unchanged",
            "GET",
            "/bookings/{{control_booking}}/payments/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(String(pm.response.json().count)).to.eql(pm.environment.get("control_payments"));',
            ],
        ),
        req(
            "W9",
            "Unknown event_type",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w9")',
                    event_type="payment.refunded_maybe",
                    provider_ref_expr='pm.environment.get("p17_ref")',
                    amount_expr='pm.environment.get("p17_amount")',
                )
            ],
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("ignored");',
            ],
            description=f"Event IGNORED row via docker shell: {SMOKE_NOTE}",
        ),
        req(
            "W10",
            "Invalid signature",
            "POST",
            "/payments/webhook/",
            body=json.dumps(
                {
                    "event_id": "evt_bad_sig",
                    "event_type": "payment.succeeded",
                    "data": {
                        "provider_reference": "x",
                        "amount": "1.00",
                        "currency": "INR",
                    },
                }
            ),
            headers=[
                ("X-Webhook-Timestamp", "{{$timestamp}}"),
                ("X-Webhook-Signature", "sha256=deadbeef"),
            ],
            tests=[status_eq(401), ENVELOPE, code_eq("INVALID_WEBHOOK_SIGNATURE")],
            description=f"No WebhookEvent row: {SMOKE_NOTE}",
        ),
        req(
            "W11",
            "Missing signature",
            "POST",
            "/payments/webhook/",
            body=json.dumps(
                {
                    "event_id": "evt_missing_sig",
                    "event_type": "payment.succeeded",
                    "data": {
                        "provider_reference": "x",
                        "amount": "1.00",
                        "currency": "INR",
                    },
                }
            ),
            headers=[("X-Webhook-Timestamp", "{{$timestamp}}")],
            tests=[status_eq(401), ENVELOPE, code_eq("INVALID_WEBHOOK_SIGNATURE")],
            description=f"No WebhookEvent row: {SMOKE_NOTE}",
        ),
        req(
            "W12",
            "Stale timestamp",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='`evt_stale_${require("uuid").v4()}`',
                    event_type="payment.succeeded",
                    provider_ref_expr='pm.environment.get("p17_ref")',
                    amount_expr='pm.environment.get("p17_amount")',
                    timestamp_js="(Math.floor(Date.now() / 1000) - 600).toString()",
                )
            ],
            tests=[status_eq(401), ENVELOPE, code_eq("INVALID_WEBHOOK_SIGNATURE")],
        ),
        req(
            "W13",
            "Malformed payload",
            "POST",
            "/payments/webhook/",
            body=json.dumps(
                {
                    "event_id": "evt_malformed",
                    "event_type": "payment.succeeded",
                }
            ),
            prereq=[
                """
const payload = {
  event_id: `evt_malformed_${require("uuid").v4()}`,
  event_type: "payment.succeeded"
};
pm.request.body.raw = JSON.stringify(payload);
"""
                + "\n"
                + SIGN_WEBHOOK
            ],
            tests=[status_eq(400), ENVELOPE, code_eq("VALIDATION_ERROR")],
            description=f"No WebhookEvent row: {SMOKE_NOTE}",
        ),
        req(
            "W14",
            "Body tampered after signing",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                """
const original = {
  event_id: `evt_tamper_${require("uuid").v4()}`,
  event_type: "payment.succeeded",
  data: {
    provider_reference: pm.environment.get("p17_ref"),
    amount: pm.environment.get("p17_amount"),
    currency: "INR"
  }
};
const tampered = JSON.parse(JSON.stringify(original));
tampered.data.amount = "1.00";
const secret = pm.environment.get("webhook_secret");
const signedBody = JSON.stringify(original);
const ts = Math.floor(Date.now() / 1000).toString();
const sig = "sha256=" + CryptoJS.HmacSHA256(signedBody, secret).toString(CryptoJS.enc.Hex);
pm.request.body.raw = JSON.stringify(tampered);
pm.request.headers.upsert({ key: "X-Webhook-Timestamp", value: ts });
pm.request.headers.upsert({ key: "X-Webhook-Signature", value: sig });
pm.request.headers.upsert({ key: "Content-Type", value: "application/json" });
""".strip()
            ],
            tests=[status_eq(401), ENVELOPE, code_eq("INVALID_WEBHOOK_SIGNATURE")],
            description=f"No WebhookEvent row: {SMOKE_NOTE}",
        ),
        req(
            "W15-book",
            "Booking for concurrent duplicates",
            "POST",
            "/bookings/",
            auth="token_a",
            body=json.dumps(
                {
                    "centre_id": "{{cid}}",
                    "test_id": "{{tid}}",
                    "appointment_at": "{{slot_11}}",
                }
            ),
            tests=[
                status_eq(201),
                'pm.environment.set("b_w15", pm.response.json().id);',
            ],
            description=(
                "W15 concurrent: Postman sends one signed event. "
                f"10 parallel identical deliveries + PROCESSED row: {SMOKE_NOTE}"
            ),
        ),
        req(
            "W15-pay",
            "Pending payment for concurrent duplicates",
            "POST",
            "/payments/",
            auth="token_a",
            headers=[("Idempotency-Key", "{{$guid}}")],
            body=json.dumps({"booking_id": "{{b_w15}}", "simulate_outcome": "PENDING"}),
            tests=[
                status_eq(201),
                """
const j = pm.response.json();
pm.environment.set("p_w15", j.id);
pm.environment.set("p_w15_ref", j.provider_reference);
pm.environment.set("p_w15_amount", String(j.amount));
""".strip(),
            ],
        ),
        req(
            "W15",
            "Concurrent duplicates (single representative)",
            "POST",
            "/payments/webhook/",
            body=w1_body,
            prereq=[
                webhook_build_and_sign(
                    event_id_expr='pm.environment.get("event_w15")',
                    event_type="payment.succeeded",
                    provider_ref_expr='pm.environment.get("p_w15_ref")',
                    amount_expr='pm.environment.get("p_w15_amount")',
                )
            ],
            tests=[
                status_eq(200),
                'pm.expect(["accepted", "duplicate"]).to.include(pm.response.json().status);',
            ],
            description=f"Full 10-way concurrent burst + PROCESSED: {SMOKE_NOTE}",
        ),
        req(
            "W15-poll-booking",
            "Booking CONFIRMED after W15",
            "GET",
            "/bookings/{{b_w15}}/",
            auth="token_a",
            tests=[
                status_eq(200),
                'pm.expect(pm.response.json().status).to.eql("CONFIRMED");',
            ],
        ),
        req(
            "W16",
            "GET webhook not allowed",
            "GET",
            "/payments/webhook/",
            tests=[status_eq(405), ENVELOPE, code_eq("METHOD_NOT_ALLOWED")],
        ),
    ]
    items.append(folder("W — Webhook", w))

    # ---- X ----
    wrong_login = json.dumps({"email": "{{email_a}}", "password": "WrongPass#1"})
    x = [
        {
            "name": "X1 — Envelope audit",
            "request": {
                "method": "GET",
                "header": [],
                "url": "{{base_url}}/health/",
                "description": (
                    "X1 audits every non-2xx response in the run for JSON error.code/"
                    "error.message and zero HTTP 500s. "
                    f"{SMOKE_NOTE}"
                ),
            },
            "event": [
                event(
                    "test",
                    "test",
                    [
                        status_eq(200),
                        'pm.test("X1 documented — full audit via make smoke", () => pm.expect(true).to.be.true);',
                    ],
                )
            ],
        },
        {
            "name": "X2 — No secrets in responses",
            "request": {
                "method": "GET",
                "header": [],
                "url": "{{base_url}}/health/",
                "description": (
                    "X2 scans every response body for password fields, hashes, "
                    "WEBHOOK_SECRET, and stack traces. "
                    f"{SMOKE_NOTE}"
                ),
            },
            "event": [
                event(
                    "test",
                    "test",
                    [
                        status_eq(200),
                        'pm.test("X2 documented — full secret scan via make smoke", () => pm.expect(true).to.be.true);',
                    ],
                )
            ],
        },
        req(
            "X3-1",
            "Wrong password 1/6",
            "POST",
            "/auth/login/",
            body=wrong_login,
            tests=[status_eq(401), ENVELOPE],
            description="Flush Redis first (`make smoke --flush-throttle` or redis-cli FLUSHDB).",
        ),
        req(
            "X3-2",
            "Wrong password 2/6",
            "POST",
            "/auth/login/",
            body=wrong_login,
            tests=[status_eq(401), ENVELOPE],
        ),
        req(
            "X3-3",
            "Wrong password 3/6",
            "POST",
            "/auth/login/",
            body=wrong_login,
            tests=[status_eq(401), ENVELOPE],
        ),
        req(
            "X3-4",
            "Wrong password 4/6",
            "POST",
            "/auth/login/",
            body=wrong_login,
            tests=[status_eq(401), ENVELOPE],
        ),
        req(
            "X3-5",
            "Wrong password 5/6",
            "POST",
            "/auth/login/",
            body=wrong_login,
            tests=[status_eq(401), ENVELOPE],
        ),
        req(
            "X3",
            "Login throttling (6th wrong password)",
            "POST",
            "/auth/login/",
            body=wrong_login,
            tests=[
                status_eq(429),
                ENVELOPE,
                code_eq("THROTTLED"),
            ],
            description=(
                "Expect 429 THROTTLED on the 6th wrong-password login within 60s. "
                "Flush Redis before the X3 sequence."
            ),
        ),
        {
            "name": "X4 — Logs are structured",
            "request": {
                "method": "GET",
                "header": [],
                "url": "{{base_url}}/health/",
                "description": (
                    "X4 checks docker compose logs web for JSON lines with request_id "
                    "and a webhook_duplicate event from W2. "
                    f"{SMOKE_NOTE}"
                ),
            },
            "event": [
                event(
                    "test",
                    "test",
                    [
                        status_eq(200),
                        'pm.test("X4 documented — log check via make smoke", () => pm.expect(true).to.be.true);',
                    ],
                )
            ],
        },
    ]
    items.append(folder("X — Cross-cutting", x))

    collection = {
        "info": {
            "name": "EVE Healthcare",
            "description": (
                "Black-box API cases matching docs/API_TEST_PLAN.md. "
                "Run top-to-bottom so tokens and IDs chain. "
                "Webhook requests sign the raw body in a pre-request script. "
                "Clock-dependent cases are marked SKIP with the covering pytest name. "
                "For the full automated matrix including concurrent races and Celery polling, use `make smoke`."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
        "variable": [
            {"key": "base_url", "value": "http://localhost:8000"},
        ],
    }

    env_keys = [
        ("base_url", "http://localhost:8000"),
        ("webhook_secret", "dev-webhook-secret"),
        ("admin_email", "admin@eve.test"),
        ("admin_password", "Clinic#Host2026"),
        ("password", "Str0ng!Pass#1"),
        ("token_a", ""),
        ("token_b", ""),
        ("token_admin", ""),
        ("refresh_a", ""),
        ("email_a", ""),
        ("email_b", ""),
        ("cid", ""),
        ("tid", ""),
        ("tid_lft", ""),
        ("tid_kft", ""),
        ("tid_xray", ""),
        ("tid_urine", ""),
        ("price", ""),
        ("b1", ""),
        ("b2", ""),
        ("b3", ""),
        ("b4", ""),
        ("b5", ""),
        ("b6", ""),
        ("b13", ""),
        ("p1", ""),
        ("p17", ""),
        ("p17_ref", ""),
        ("p17_amount", ""),
        ("idem_p1", ""),
        ("event_w1", ""),
        ("event_w4", ""),
        ("event_w5", ""),
        ("event_w6", ""),
        ("event_w7", ""),
        ("event_w8", ""),
        ("event_w9", ""),
        ("event_w15", ""),
        ("new_centre", ""),
        ("deleted_centre", ""),
        ("added_test", ""),
        ("slot_1", ""),
        ("slot_2", ""),
        ("slot_3", ""),
        ("slot_4", ""),
        ("slot_5", ""),
        ("slot_6", ""),
        ("slot_7", ""),
        ("slot_8", ""),
        ("slot_9", ""),
        ("slot_10", ""),
        ("slot_11", ""),
        ("slot_12", ""),
        ("run_ts", ""),
        ("control_booking", ""),
        ("control_payments", ""),
        ("b_w4", ""),
        ("p_w4", ""),
        ("b_w6", ""),
        ("p_w6", ""),
        ("b_w7", ""),
        ("p_w7", ""),
        ("b_w15", ""),
        ("p_w15", ""),
    ]
    env = {
        "id": "eve-local",
        "name": "EVE Healthcare local",
        "values": [
            {"key": k, "value": v, "enabled": True} for k, v in env_keys
        ],
        "_postman_variable_scope": "environment",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    collection_path = OUT / "EVE_Healthcare.postman_collection.json"
    env_path = OUT / "local.postman_environment.json"
    collection_path.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    env_path.write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")

    def count_requests(nodes: list) -> int:
        total = 0
        for node in nodes:
            if "item" in node:
                total += count_requests(node["item"])
            else:
                total += 1
        return total

    n = count_requests(items)
    print(f"Wrote {collection_path}")
    print(f"Wrote {env_path}")
    print(f"Request count: {n}")


if __name__ == "__main__":
    main()
