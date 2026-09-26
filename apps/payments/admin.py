from django.contrib import admin

from apps.payments.models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "provider_reference",
        "user",
        "booking",
        "amount",
        "currency",
        "status",
        "created_at",
    )
    list_filter = ("status", "currency")
    search_fields = ("provider_reference", "idempotency_key", "user__email", "booking__id")
    readonly_fields = ("created_at", "updated_at")
