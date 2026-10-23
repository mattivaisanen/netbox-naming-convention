from django.urls import include, path

from utilities.urls import get_model_urls

from . import views  # noqa: F401 - registers the model views

APP = 'netbox_naming_convention'

urlpatterns = [
    path('rules/', include(get_model_urls(APP, 'namingrule', detail=False))),
    path('rules/<int:pk>/', include(get_model_urls(APP, 'namingrule'))),
]
