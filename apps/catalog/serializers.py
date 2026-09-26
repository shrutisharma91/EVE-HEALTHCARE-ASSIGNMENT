from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest, SampleType
from apps.catalog.validators import validate_pincode
from apps.core.serializers import StrictSerializer


class CentreSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticCentre
        fields = [
            "id",
            "name",
            "address",
            "city",
            "pincode",
            "latitude",
            "longitude",
            "phone",
            "is_active",
        ]


class OfferedTestSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="test.id", read_only=True)
    code = serializers.CharField(source="test.code", read_only=True)
    name = serializers.CharField(source="test.name", read_only=True)
    description = serializers.CharField(source="test.description", read_only=True)
    sample_type = serializers.CharField(source="test.sample_type", read_only=True)

    class Meta:
        model = CentreTest
        fields = [
            "id",
            "code",
            "name",
            "description",
            "sample_type",
            "price",
            "is_available",
        ]


class CentreDetailSerializer(CentreSerializer):
    tests = OfferedTestSerializer(source="offerings", many=True, read_only=True)

    class Meta(CentreSerializer.Meta):
        fields = [*CentreSerializer.Meta.fields, "tests"]


class TestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ["id", "code", "name", "description", "sample_type", "is_active"]


class CentreWriteSerializer(StrictSerializer):
    name = serializers.CharField(max_length=255)
    address = serializers.CharField()
    city = serializers.CharField(max_length=100)
    pincode = serializers.CharField(max_length=6, validators=[validate_pincode])
    phone = serializers.CharField(max_length=20)
    latitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
    )
    longitude = serializers.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=False,
        allow_null=True,
    )

    def validate_name(self, value: str) -> str:
        return _nonblank(value, "name")

    def validate_address(self, value: str) -> str:
        return _nonblank(value, "address")

    def validate_city(self, value: str) -> str:
        return _nonblank(value, "city")

    def validate_phone(self, value: str) -> str:
        return _nonblank(value, "phone")

    def validate_latitude(self, value):
        return _check_latitude(value)

    def validate_longitude(self, value):
        return _check_longitude(value)


class CentreUpdateSerializer(CentreWriteSerializer):
    name = serializers.CharField(max_length=255, required=False)
    address = serializers.CharField(required=False)
    city = serializers.CharField(max_length=100, required=False)
    pincode = serializers.CharField(max_length=6, required=False, validators=[validate_pincode])
    phone = serializers.CharField(max_length=20, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        return attrs


class TestWriteSerializer(StrictSerializer):
    code = serializers.CharField(max_length=32)
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    sample_type = serializers.ChoiceField(choices=SampleType.choices)
    is_active = serializers.BooleanField(required=False)

    def validate_code(self, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned

    def validate_name(self, value: str) -> str:
        return _nonblank(value, "name")


class TestUpdateSerializer(TestWriteSerializer):
    code = serializers.CharField(max_length=32, required=False)
    name = serializers.CharField(max_length=255, required=False)
    sample_type = serializers.ChoiceField(choices=SampleType.choices, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        return attrs


class CentreTestWriteSerializer(StrictSerializer):
    test_id = serializers.UUIDField()
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    is_available = serializers.BooleanField(required=False, default=True)


class CentreTestUpdateSerializer(StrictSerializer):
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )
    is_available = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide price or is_available.")
        return attrs


def _nonblank(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise serializers.ValidationError("This field may not be blank.")
    return cleaned


def _check_latitude(value):
    if value is not None and not Decimal("-90") <= value <= Decimal("90"):
        raise serializers.ValidationError("Latitude must be between -90 and 90.")
    return value


def _check_longitude(value):
    if value is not None and not Decimal("-180") <= value <= Decimal("180"):
        raise serializers.ValidationError("Longitude must be between -180 and 180.")
    return value
