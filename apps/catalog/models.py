from django.db import models
from django.db.models import Q

from apps.catalog.validators import validate_pincode
from apps.core.models import TimeStampedModel, UUIDModel


class SampleType(models.TextChoices):
    BLOOD = "BLOOD", "Blood"
    URINE = "URINE", "Urine"
    IMAGING = "IMAGING", "Imaging"
    OTHER = "OTHER", "Other"


class DiagnosticCentre(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=255)
    address = models.TextField()
    city = models.CharField(max_length=100, db_index=True)
    pincode = models.CharField(max_length=6, validators=[validate_pincode])
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    phone = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["city", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "city"], name="unique_centre_name_city"),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.city}"


class DiagnosticTest(UUIDModel, TimeStampedModel):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    sample_type = models.CharField(max_length=16, choices=SampleType.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class CentreTest(TimeStampedModel):
    """A test offered by one centre at that centre's own price."""

    centre = models.ForeignKey(
        DiagnosticCentre,
        on_delete=models.PROTECT,
        related_name="offerings",
    )
    test = models.ForeignKey(
        DiagnosticTest,
        on_delete=models.PROTECT,
        related_name="centre_offerings",
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["centre", "test"], name="unique_centre_test"),
            models.CheckConstraint(condition=Q(price__gt=0), name="centre_test_price_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.centre} — {self.test.code}"
