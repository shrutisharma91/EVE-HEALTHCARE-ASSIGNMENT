from django.contrib import admin

from apps.payments.models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "provider_reference",
        "user",
        "booking",
        "amount",
        "currency",
        "status",
        "refund_required",
        "created_at",
    )
    list_filter = ("status", "currency", "refund_required")
    search_fields = ("provider_reference", "idempotency_key", "user__email", "booking__id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "processing_status", "attempts", "received_at")
    list_filter = ("processing_status", "event_type")
    search_fields = ("event_id", "payment__provider_reference")
    readonly_fields = ("payload", "received_at", "processed_at", "created_at", "updated_at")
