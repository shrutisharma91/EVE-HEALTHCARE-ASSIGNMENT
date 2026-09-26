from rest_framework import serializers

from apps.core.serializers import StrictSerializer
from apps.payments.models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    booking_id = serializers.UUIDField(read_only=True)
    booking_status = serializers.CharField(source="booking.status", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "booking_id",
            "amount",
            "currency",
            "status",
            "provider_reference",
            "failure_reason",
            "idempotency_key",
            "booking_status",
            "created_at",
        ]
        read_only_fields = fields


class PaymentCreateSerializer(StrictSerializer):
    booking_id = serializers.UUIDField()
    simulate_outcome = serializers.ChoiceField(
        choices=["SUCCESS", "FAILED"],
        required=False,
    )

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        if hasattr(data, "pop"):
            data.pop("amount", None)
        return super().to_internal_value(data)
