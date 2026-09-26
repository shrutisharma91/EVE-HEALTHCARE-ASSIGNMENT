import factory
from django.contrib.auth import get_user_model

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
