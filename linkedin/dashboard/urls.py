# linkedin/dashboard/urls.py
from django.urls import path

from linkedin.dashboard import views

urlpatterns = [
    path("", views.dashboard_page, name="dashboard"),
    path("api/kpis/", views.api_kpis, name="dashboard_api_kpis"),
    path("api/senders/", views.api_senders, name="dashboard_api_senders"),
    path("api/sequences/", views.api_sequences, name="dashboard_api_sequences"),
    path("api/sequence/<int:sequence_id>/", views.api_sequence, name="dashboard_api_sequence"),
]
