import json

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import StandardPagination
from apps.core.serializers import ErrorEnvelopeSerializer
from apps.payments.exceptions import IdempotencyKeyRequired
from apps.payments.ingress import accept_webhook
from apps.payments.selectors import get_own_payment, payments_for_booking
from apps.payments.serializers import PaymentCreateSerializer, PaymentSerializer, WebhookSerializer
from apps.payments.services import create_payment
from apps.payments.signing import verify_webhook


class PaymentCreateView(APIView):
    @extend_schema(
        tags=["Payments"],
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    "Client-chosen unique key for this payment attempt. "
                    "Any non-empty string works (e.g. pay-001 or a UUID). "
                    "Replay the same key to get the original payment; "
                    "reusing it for a different booking returns 422."
                ),
                examples=[
                    OpenApiExample("Simple key", value="pay-001"),
                    OpenApiExample("UUID key", value="a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
                ],
            ),
        ],
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
            ),
            OpenApiExample(
                "Leave pending for the webhook",
                value={
                    "booking_id": "6b0b1c2e-1a2b-4c3d-8e9f-112233445566",
                    "simulate_outcome": "PENDING",
                },
                request_only=True,
            ),
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


class WebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        tags=["Payments"],
        auth=[],
        request=WebhookSerializer,
        responses={200: dict, 400: ErrorEnvelopeSerializer, 401: ErrorEnvelopeSerializer},
        examples=[
            OpenApiExample(
                "Payment succeeded",
                value={
                    "event_id": "evt_123",
                    "event_type": "payment.succeeded",
                    "data": {
                        "provider_reference": "sim_pay_abc",
                        "amount": "499.00",
                        "currency": "INR",
                    },
                    "created_at": "2026-09-26T10:00:00Z",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        verify_webhook(
            request.body,
            request.headers.get("X-Webhook-Signature", ""),
            request.headers.get("X-Webhook-Timestamp", ""),
        )
        try:
            payload = json.loads(request.body.decode() or "")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise exceptions.ParseError("Malformed request body.") from exc
        serializer = WebhookSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        result = accept_webhook(
            event_id=serializer.validated_data["event_id"],
            event_type=serializer.validated_data["event_type"],
            payload=payload,
        )
        return Response(result)


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
