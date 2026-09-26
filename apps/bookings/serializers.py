from rest_framework import serializers

from apps.bookings.models import Booking
from apps.core.serializers import StrictSerializer


class BookingSerializer(serializers.ModelSerializer):
    centre_id = serializers.UUIDField(source="centre.id", read_only=True)
    centre_name = serializers.CharField(source="centre.name", read_only=True)
    test_id = serializers.UUIDField(source="test.id", read_only=True)
    test_code = serializers.CharField(source="test.code", read_only=True)
    test_name = serializers.CharField(source="test.name", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "centre_id",
            "centre_name",
            "test_id",
            "test_code",
            "test_name",
            "appointment_at",
            "amount",
            "status",
            "cancelled_at",
            "cancellation_reason",
            "created_at",
        ]
        read_only_fields = fields


class BookingCreateSerializer(StrictSerializer):
    centre_id = serializers.UUIDField()
    test_id = serializers.UUIDField()
    appointment_at = serializers.DateTimeField()

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        if hasattr(data, "pop"):
            data.pop("amount", None)
        return super().to_internal_value(data)


class BookingCancelSerializer(StrictSerializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate_reason(self, value: str) -> str:
        return value.strip()
