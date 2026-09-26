from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.selectors import filter_bookings, get_visible_booking
from apps.bookings.serializers import (
    BookingCancelSerializer,
    BookingCreateSerializer,
    BookingSerializer,
)
from apps.bookings.services import cancel_booking, create_booking
from apps.core.pagination import StandardPagination
from apps.core.serializers import ErrorEnvelopeSerializer


class BookingListCreateView(APIView):
    @extend_schema(
        tags=["Bookings"],
        request=BookingCreateSerializer,
        responses={
            201: BookingSerializer,
            400: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Create booking",
                value={
                    "centre_id": "6b0b1c2e-1a2b-4c3d-8e9f-112233445566",
                    "test_id": "7c1c2d3e-2b3c-4d4e-9f0a-223344556677",
                    "appointment_at": "2026-10-01T10:00:00+05:30",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = create_booking(user=request.user, **serializer.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["Bookings"], responses={200: BookingSerializer(many=True)})
    def get(self, request):
        queryset = filter_bookings(request.user, request.query_params)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(BookingSerializer(page, many=True).data)


class BookingDetailView(APIView):
    @extend_schema(
        tags=["Bookings"],
        responses={200: BookingSerializer, 404: ErrorEnvelopeSerializer},
    )
    def get(self, request, booking_id):
        booking = get_visible_booking(request.user, booking_id)
        return Response(BookingSerializer(booking).data)


class BookingCancelView(APIView):
    @extend_schema(
        tags=["Bookings"],
        request=BookingCancelSerializer,
        responses={
            200: BookingSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request, booking_id):
        serializer = BookingCancelSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        booking = cancel_booking(
            user=request.user,
            booking_id=booking_id,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(BookingSerializer(booking).data)
