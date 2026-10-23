from django.urls import path

from netbox.api.routers import NetBoxRouter

from . import views

router = NetBoxRouter()
router.APIRootView = views.NamingConventionRootView
router.register('rules', views.NamingRuleViewSet)

urlpatterns = [
    path('suggest/', views.SuggestView.as_view(), name='suggest'),
    *router.urls,
]
