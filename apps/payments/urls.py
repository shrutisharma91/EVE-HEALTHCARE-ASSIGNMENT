from django.urls import path

from apps.payments.views import (
    BookingPaymentsView,
    PaymentCreateView,
    PaymentDetailView,
    WebhookView,
)

urlpatterns = [
    path("payments/webhook/", WebhookView.as_view(), name="payment-webhook"),
    path("payments/", PaymentCreateView.as_view(), name="payment-create"),
    path("payments/<uuid:payment_id>/", PaymentDetailView.as_view(), name="payment-detail"),
    path(
        "bookings/<uuid:booking_id>/payments/",
        BookingPaymentsView.as_view(),
        name="booking-payments",
    ),
]
