from django.urls import path

from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.APIRootView = views.NamingConventionRootView
router.register('rules', views.NamingRuleViewSet)
router.register('reservations', views.ReservedNameViewSet)

urlpatterns = [
    path('suggest/', views.SuggestView.as_view(), name='suggest'),
    path('reserve/', views.ReserveView.as_view(), name='reserve'),
    *router.urls,
]
