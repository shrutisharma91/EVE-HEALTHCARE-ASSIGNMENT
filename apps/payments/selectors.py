from django.shortcuts import get_object_or_404

from apps.bookings.models import Booking
from apps.payments.models import Payment


def get_own_payment(user, payment_id) -> Payment:
    queryset = Payment.objects.select_related("booking")
    if not user.is_staff:
        queryset = queryset.filter(user=user)
    return get_object_or_404(queryset, pk=payment_id)


def payments_for_booking(user, booking_id):
    bookings = Booking.objects.all() if user.is_staff else Booking.objects.filter(user=user)
    booking = get_object_or_404(bookings, pk=booking_id)
    return booking.payments.select_related("booking").order_by("-created_at", "-id")
