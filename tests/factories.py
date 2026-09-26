from decimal import Decimal

import factory
from django.contrib.auth import get_user_model

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@eve.test")
    full_name = "Test User"
    phone = "9876543210"
    is_active = True
    is_staff = False

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        raw_password = kwargs.pop("password", "Str0ng!Passw0rd")
        user = model_class(*args, **kwargs)
        user.set_password(raw_password)
        user.save()
        return user


class DiagnosticCentreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DiagnosticCentre

    name = factory.Sequence(lambda n: f"EVE Centre {n}")
    address = "12 Health Street"
    city = "Bengaluru"
    pincode = "560001"
    phone = "08041234567"
    is_active = True


class DiagnosticTestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DiagnosticTest

    code = factory.Sequence(lambda n: f"T{n:03d}")
    name = factory.Sequence(lambda n: f"Test {n}")
    description = ""
    sample_type = "BLOOD"
    is_active = True


class CentreTestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CentreTest

    centre = factory.SubFactory(DiagnosticCentreFactory)
    test = factory.SubFactory(DiagnosticTestFactory)
    price = Decimal("499.00")
    is_available = True
