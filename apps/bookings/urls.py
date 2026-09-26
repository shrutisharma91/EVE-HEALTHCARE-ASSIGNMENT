from django.urls import path

from apps.bookings.views import BookingCancelView, BookingDetailView, BookingListCreateView

urlpatterns = [
    path("bookings/", BookingListCreateView.as_view(), name="booking-list"),
    path("bookings/<uuid:booking_id>/", BookingDetailView.as_view(), name="booking-detail"),
    path("bookings/<uuid:booking_id>/cancel/", BookingCancelView.as_view(), name="booking-cancel"),
]
