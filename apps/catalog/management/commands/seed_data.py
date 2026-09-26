"""Idempotent demo data: centres, tests, an admin and a patient."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.catalog.cache import invalidate_centre_list_cache
from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest, SampleType

ADMIN_EMAIL = "admin@eve.test"
ADMIN_PASSWORD = "Clinic#Host2026"
DEMO_EMAIL = "demo@eve.test"
DEMO_PASSWORD = "Patient#Host2026"

CENTRES = [
    {
        "name": "EVE Diagnostics Guwahati",
        "address": "GS Road, Christian Basti",
        "city": "Guwahati",
        "pincode": "781005",
        "phone": "03612345678",
        "latitude": Decimal("26.144518"),
        "longitude": Decimal("91.736237"),
    },
    {
        "name": "EVE Diagnostics Bengaluru",
        "address": "12 MG Road",
        "city": "Bengaluru",
        "pincode": "560001",
        "phone": "08041234567",
        "latitude": Decimal("12.975800"),
        "longitude": Decimal("77.606000"),
    },
    {
        "name": "EVE Diagnostics Delhi",
        "address": "Connaught Place, Block A",
        "city": "Delhi",
        "pincode": "110001",
        "phone": "01141234567",
        "latitude": Decimal("28.631500"),
        "longitude": Decimal("77.216700"),
    },
    {
        "name": "EVE Diagnostics Mumbai",
        "address": "Nariman Point",
        "city": "Mumbai",
        "pincode": "400021",
        "phone": "02241234567",
        "latitude": Decimal("18.925600"),
        "longitude": Decimal("72.824200"),
    },
    {
        "name": "EVE Diagnostics Pune",
        "address": "FC Road, Shivajinagar",
        "city": "Pune",
        "pincode": "411004",
        "phone": "02041234567",
        "latitude": Decimal("18.530800"),
        "longitude": Decimal("73.847500"),
    },
]

TESTS = [
    (
        "CBC",
        "Complete Blood Count",
        "Blood counts and indices.",
        SampleType.BLOOD,
        Decimal("450.00"),
    ),
    (
        "LFT",
        "Liver Function Test",
        "Liver enzymes and bilirubin.",
        SampleType.BLOOD,
        Decimal("700.00"),
    ),
    (
        "KFT",
        "Kidney Function Test",
        "Creatinine, urea and electrolytes.",
        SampleType.BLOOD,
        Decimal("650.00"),
    ),
    (
        "LIPID",
        "Lipid Profile",
        "Cholesterol and triglycerides.",
        SampleType.BLOOD,
        Decimal("800.00"),
    ),
    (
        "HBA1C",
        "HbA1c",
        "Average blood glucose over three months.",
        SampleType.BLOOD,
        Decimal("550.00"),
    ),
    ("THYROID", "Thyroid Profile", "TSH, T3 and T4.", SampleType.BLOOD, Decimal("900.00")),
    ("VITD", "Vitamin D", "25-hydroxy vitamin D.", SampleType.BLOOD, Decimal("1200.00")),
    (
        "URINE",
        "Urine Routine",
        "Physical, chemical and microscopic urine exam.",
        SampleType.URINE,
        Decimal("250.00"),
    ),
    ("XRAY_CHEST", "X-Ray Chest", "Chest radiograph.", SampleType.IMAGING, Decimal("600.00")),
    ("ECG", "ECG", "12-lead electrocardiogram.", SampleType.OTHER, Decimal("400.00")),
]

# Not every centre offers every test. Prices are scaled per city.
CITY_FACTOR = {
    "Guwahati": Decimal("0.90"),
    "Bengaluru": Decimal("1.15"),
    "Delhi": Decimal("1.10"),
    "Mumbai": Decimal("1.20"),
    "Pune": Decimal("1.05"),
}
SKIPPED = {
    ("Guwahati", "XRAY_CHEST"),
    ("Guwahati", "ECG"),
    ("Pune", "ECG"),
}


class Command(BaseCommand):
    help = "Load demo centres, tests, an admin and a patient. Safe to run more than once."

    def handle(self, *args, **options):
        with transaction.atomic():
            self._user(ADMIN_EMAIL, ADMIN_PASSWORD, "EVE Admin", "9999999999", staff=True)
            self._user(DEMO_EMAIL, DEMO_PASSWORD, "EVE Demo", "9876543210", staff=False)
            centres = [self._centre(row) for row in CENTRES]
            tests = {
                code: self._test(code, name, description, sample)
                for code, name, description, sample, _ in TESTS
            }
            for centre in centres:
                factor = CITY_FACTOR[centre.city]
                for code, _name, _description, _sample, base in TESTS:
                    if (centre.city, code) in SKIPPED:
                        continue
                    price = (base * factor).quantize(Decimal("0.01"))
                    CentreTest.objects.get_or_create(
                        centre=centre,
                        test=tests[code],
                        defaults={"price": price, "is_available": True},
                    )
        invalidate_centre_list_cache()
        self.stdout.write(self.style.SUCCESS("Seed data is ready."))

    def _user(self, email, password, full_name, phone, *, staff):
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "full_name": full_name,
                "phone": phone,
                "is_staff": staff,
                "is_superuser": staff,
            },
        )
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
        elif staff and (not user.is_staff or not user.is_superuser):
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])
        return user

    def _centre(self, row):
        centre, _created = DiagnosticCentre.objects.get_or_create(
            name=row["name"],
            city=row["city"],
            defaults=row,
        )
        return centre

    def _test(self, code, name, description, sample_type):
        test, _created = DiagnosticTest.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "sample_type": sample_type,
                "is_active": True,
            },
        )
        return test
