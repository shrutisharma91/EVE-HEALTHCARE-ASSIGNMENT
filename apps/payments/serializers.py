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
            "refund_required",
            "idempotency_key",
            "booking_status",
            "created_at",
        ]
        read_only_fields = fields


class WebhookDataSerializer(serializers.Serializer):
    provider_reference = serializers.CharField(max_length=64)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.CharField(max_length=3)


class WebhookSerializer(serializers.Serializer):
    """Gateway payloads may grow new fields; ignore unknowns instead of 400."""

    event_id = serializers.CharField(max_length=255)
    event_type = serializers.CharField(max_length=64)
    data = WebhookDataSerializer()
    created_at = serializers.DateTimeField()


class PaymentCreateSerializer(StrictSerializer):
    booking_id = serializers.UUIDField()
    simulate_outcome = serializers.ChoiceField(
        choices=["SUCCESS", "FAILED", "PENDING"],
        required=False,
        help_text=(
            "SUCCESS and FAILED settle inline. PENDING leaves the payment "
            "INITIATED until a signed webhook arrives."
        ),
    )

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        if hasattr(data, "pop"):
            data.pop("amount", None)
        return super().to_internal_value(data)
