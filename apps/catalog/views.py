from contextlib import suppress

from django.core.cache import cache
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.cache import CENTRE_LIST_TTL_SECONDS, centre_list_cache_key
from apps.catalog.selectors import filter_centres, filter_tests, get_centre
from apps.catalog.serializers import (
    CentreDetailSerializer,
    CentreSerializer,
    CentreTestUpdateSerializer,
    CentreTestWriteSerializer,
    CentreUpdateSerializer,
    CentreWriteSerializer,
    OfferedTestSerializer,
    TestSerializer,
    TestUpdateSerializer,
    TestWriteSerializer,
)
from apps.catalog.services import (
    add_centre_test,
    create_centre,
    create_test,
    deactivate_centre,
    remove_centre_test,
    update_centre,
    update_centre_test,
    update_test,
)
from apps.core.pagination import StandardPagination
from apps.core.permissions import IsStaffOrReadOnly
from apps.core.serializers import ErrorEnvelopeSerializer


class CentreListCreateView(APIView):
    permission_classes = [IsStaffOrReadOnly]

    @extend_schema(
        tags=["Catalog"],
        auth=[],
        responses={200: CentreSerializer(many=True)},
        examples=[
            OpenApiExample(
                "Centre page",
                value={
                    "count": 1,
                    "next": None,
                    "previous": None,
                    "results": [
                        {
                            "id": "6b0b1c2e-1a2b-4c3d-8e9f-112233445566",
                            "name": "EVE Diagnostics Bengaluru",
                            "address": "12 MG Road",
                            "city": "Bengaluru",
                            "pincode": "560001",
                            "latitude": "12.971600",
                            "longitude": "77.594600",
                            "phone": "08041234567",
                            "is_active": True,
                        }
                    ],
                },
                response_only=True,
            )
        ],
    )
    def get(self, request):
        cache_key = centre_list_cache_key(request.query_params)
        try:
            cached = cache.get(cache_key)
        except Exception:
            cached = None
        if cached is not None:
            return Response(cached)
        queryset = filter_centres(request.query_params)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        payload = paginator.get_paginated_response(CentreSerializer(page, many=True).data).data
        with suppress(Exception):
            cache.set(cache_key, payload, CENTRE_LIST_TTL_SECONDS)
        return Response(payload)

    @extend_schema(
        tags=["Catalog"],
        request=CentreWriteSerializer,
        responses={
            201: CentreSerializer,
            400: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request):
        serializer = CentreWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        centre = create_centre(**serializer.validated_data)
        return Response(CentreSerializer(centre).data, status=status.HTTP_201_CREATED)


class CentreDetailView(APIView):
    permission_classes = [IsStaffOrReadOnly]

    @extend_schema(
        tags=["Catalog"],
        auth=[],
        responses={200: CentreDetailSerializer, 404: ErrorEnvelopeSerializer},
    )
    def get(self, request, centre_id):
        centre = get_centre(centre_id, include_inactive=request.user.is_staff)
        return Response(CentreDetailSerializer(centre).data)

    @extend_schema(
        tags=["Catalog"],
        request=CentreUpdateSerializer,
        responses={
            200: CentreDetailSerializer,
            400: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request, centre_id):
        serializer = CentreUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_centre(centre_id=centre_id, **serializer.validated_data)
        centre = get_centre(centre_id, include_inactive=True)
        return Response(CentreDetailSerializer(centre).data)

    @extend_schema(tags=["Catalog"], responses={204: None, 404: ErrorEnvelopeSerializer})
    def delete(self, request, centre_id):
        deactivate_centre(centre_id=centre_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CentreTestListCreateView(APIView):
    permission_classes = [IsStaffOrReadOnly]

    @extend_schema(
        tags=["Catalog"],
        auth=[],
        responses={200: OfferedTestSerializer(many=True), 404: ErrorEnvelopeSerializer},
    )
    def get(self, request, centre_id):
        centre = get_centre(centre_id, include_inactive=request.user.is_staff)
        return Response(OfferedTestSerializer(centre.offerings.all(), many=True).data)

    @extend_schema(
        tags=["Catalog"],
        request=CentreTestWriteSerializer,
        responses={
            201: OfferedTestSerializer,
            400: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
            409: ErrorEnvelopeSerializer,
        },
    )
    def post(self, request, centre_id):
        serializer = CentreTestWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offering = add_centre_test(centre_id=centre_id, **serializer.validated_data)
        return Response(OfferedTestSerializer(offering).data, status=status.HTTP_201_CREATED)


class CentreTestDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        tags=["Catalog"],
        request=CentreTestUpdateSerializer,
        responses={
            200: OfferedTestSerializer,
            400: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
    )
    def patch(self, request, centre_id, test_id):
        serializer = CentreTestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offering = update_centre_test(
            centre_id=centre_id,
            test_id=test_id,
            **serializer.validated_data,
        )
        return Response(OfferedTestSerializer(offering).data)

    @extend_schema(tags=["Catalog"], responses={204: None, 404: ErrorEnvelopeSerializer})
    def delete(self, request, centre_id, test_id):
        remove_centre_test(centre_id=centre_id, test_id=test_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TestListCreateView(APIView):
    permission_classes = [IsStaffOrReadOnly]

    @extend_schema(tags=["Catalog"], auth=[], responses={200: TestSerializer(many=True)})
    def get(self, request):
        queryset = filter_tests(request.query_params, include_inactive=request.user.is_staff)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(TestSerializer(page, many=True).data)

    @extend_schema(
        tags=["Catalog"],
        request=TestWriteSerializer,
        responses={201: TestSerializer, 400: ErrorEnvelopeSerializer, 409: ErrorEnvelopeSerializer},
    )
    def post(self, request):
        serializer = TestWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test = create_test(**serializer.validated_data)
        return Response(TestSerializer(test).data, status=status.HTTP_201_CREATED)


class TestDetailView(APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        tags=["Catalog"],
        request=TestUpdateSerializer,
        responses={200: TestSerializer, 400: ErrorEnvelopeSerializer, 404: ErrorEnvelopeSerializer},
    )
    def patch(self, request, test_id):
        serializer = TestUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        test = update_test(test_id=test_id, **serializer.validated_data)
        return Response(TestSerializer(test).data)
