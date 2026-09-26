from django.contrib import admin

from apps.bookings.models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "centre", "test", "appointment_at", "amount", "status")
    list_filter = ("status", "centre__city")
    search_fields = ("user__email", "centre__name", "test__code", "id")
    readonly_fields = ("amount", "created_at", "updated_at", "cancelled_at")
