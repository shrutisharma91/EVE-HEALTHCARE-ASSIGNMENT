from django.shortcuts import get_object_or_404

from apps.bookings.models import Booking
from apps.payments.models import Payment


def get_own_payment(user, payment_id) -> Payment:
    return get_object_or_404(
        Payment.objects.select_related("booking").filter(user=user),
        pk=payment_id,
    )


def payments_for_booking(user, booking_id):
    booking = get_object_or_404(Booking.objects.filter(user=user), pk=booking_id)
    return booking.payments.select_related("booking").order_by("-created_at", "-id")
