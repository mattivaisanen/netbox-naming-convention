from django.urls import include, path

from utilities.urls import get_model_urls

from . import views

APP = 'netbox_naming_convention'

urlpatterns = [
    path('rules/', include(get_model_urls(APP, 'namingrule', detail=False))),
    path('rules/<int:pk>/', include(get_model_urls(APP, 'namingrule'))),
    path('report/', views.NamingReportView.as_view(), name='report'),
    path('report/rename/', views.NamingReportRenameView.as_view(), name='report_rename'),
    path('reference/', views.TemplateReferenceView.as_view(), name='reference'),
]
