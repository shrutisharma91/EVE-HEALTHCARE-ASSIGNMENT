from django.contrib import admin

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest


@admin.register(DiagnosticCentre)
class DiagnosticCentreAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "pincode", "phone", "is_active", "created_at")
    list_filter = ("is_active", "city")
    search_fields = ("name", "city", "pincode", "phone")


@admin.register(DiagnosticTest)
class DiagnosticTestAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "sample_type", "is_active")
    list_filter = ("sample_type", "is_active")
    search_fields = ("code", "name")


@admin.register(CentreTest)
class CentreTestAdmin(admin.ModelAdmin):
    list_display = ("centre", "test", "price", "is_available")
    list_filter = ("is_available", "test__sample_type")
    search_fields = ("centre__name", "centre__city", "test__code", "test__name")
