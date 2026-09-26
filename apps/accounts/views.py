from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.serializers import (
    LoginSerializer,
    SignupResponseSerializer,
    SignupSerializer,
    TokenPairSerializer,
    UserSerializer,
)
from apps.accounts.services import login, signup
from apps.core.serializers import ErrorEnvelopeSerializer


class SignupView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=["Auth"],
        auth=[],
        request=SignupSerializer,
        responses={
            201: SignupResponseSerializer,
            400: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Signup",
                value={
                    "email": "ada@eve.test",
                    "password": "Str0ng!Passw0rd",
                    "full_name": "Ada Lovelace",
                    "phone": "9876543210",
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, access, refresh = signup(**serializer.validated_data)
        payload = SignupResponseSerializer({"user": user, "access": access, "refresh": refresh})
        return Response(payload.data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=["Auth"],
        auth=[],
        request=LoginSerializer,
        responses={
            200: TokenPairSerializer,
            400: ErrorEnvelopeSerializer,
            401: ErrorEnvelopeSerializer,
        },
        examples=[
            OpenApiExample(
                "Login",
                value={"email": "ada@eve.test", "password": "Str0ng!Passw0rd"},
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access, refresh = login(**serializer.validated_data)
        return Response({"access": access, "refresh": refresh})


class RefreshView(TokenRefreshView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Auth"],
        auth=[],
        responses={200: TokenPairSerializer, 401: ErrorEnvelopeSerializer},
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], responses={200: UserSerializer, 401: ErrorEnvelopeSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)
