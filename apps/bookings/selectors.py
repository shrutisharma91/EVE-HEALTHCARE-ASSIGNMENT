from django.shortcuts import get_object_or_404

from apps.bookings.exceptions import InvalidInput
from apps.bookings.models import Booking, BookingStatus


def visible_bookings(user):
    """Owners see their rows. Staff see every booking. Anyone else gets an empty set."""
    queryset = Booking.objects.select_related("centre", "test").order_by("-created_at", "-id")
    if user.is_staff:
        return queryset
    return queryset.filter(user=user)


def filter_bookings(user, params):
    queryset = visible_bookings(user)
    status = params.get("status")
    if status:
        if status not in BookingStatus.values:
            raise InvalidInput({"status": ["Select a valid booking status."]})
        queryset = queryset.filter(status=status)
    return queryset


def get_visible_booking(user, booking_id) -> Booking:
    return get_object_or_404(visible_bookings(user), pk=booking_id)
