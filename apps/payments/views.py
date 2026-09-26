from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.serializers import ErrorEnvelopeSerializer
from apps.payments.exceptions import IdempotencyKeyRequired
from apps.payments.selectors import get_own_payment, payments_for_booking
from apps.payments.serializers import PaymentCreateSerializer, PaymentSerializer
from apps.payments.services import create_payment


class PaymentCreateView(APIView):
    @extend_schema(
        tags=["Payments"],
        request=PaymentCreateSerializer,
        responses={
            201: PaymentSerializer,
            200: PaymentSerializer,
            400: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
            422: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Simulate success",
                value={
                    "booking_id": "6b0b1c2e-1a2b-4c3d-8e9f-112233445566",
                    "simulate_outcome": "SUCCESS",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        key = request.headers.get("Idempotency-Key", "")
        if not str(key).strip():
            raise IdempotencyKeyRequired()
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment, created = create_payment(
            user=request.user,
            idempotency_key=key,
            **serializer.validated_data,
        )
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(PaymentSerializer(payment).data, status=code)


class PaymentDetailView(APIView):
    @extend_schema(
        tags=["Payments"],
        responses={200: PaymentSerializer, 404: ErrorEnvelopeSerializer},
    )
    def get(self, request, payment_id):
        payment = get_own_payment(request.user, payment_id)
        return Response(PaymentSerializer(payment).data)


class BookingPaymentsView(APIView):
    @extend_schema(tags=["Payments"], responses={200: PaymentSerializer(many=True)})
    def get(self, request, booking_id):
        queryset = payments_for_booking(request.user, booking_id)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(PaymentSerializer(page, many=True).data)
