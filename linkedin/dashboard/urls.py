# linkedin/dashboard/urls.py
from django.urls import path

from linkedin.dashboard import views

urlpatterns = [
    path("", views.dashboard_page, name="dashboard"),
    path("api/kpis/", views.api_kpis, name="dashboard_api_kpis"),
    path("api/senders/", views.api_senders, name="dashboard_api_senders"),
    path("api/sequences/", views.api_sequences, name="dashboard_api_sequences"),
    path("api/sequence/<int:sequence_id>/", views.api_sequence, name="dashboard_api_sequence"),
    path("api/step/<int:step_id>/", views.api_update_step, name="dashboard_api_update_step"),
    path("api/sequences/create/", views.api_create_sequence, name="dashboard_api_create_sequence"),
    path("api/sequence/<int:sequence_id>/step/", views.api_create_step, name="dashboard_api_create_step"),
    path("api/leads/", views.api_leads, name="dashboard_api_leads"),
    path("api/leads/csv/", views.api_leads_csv, name="dashboard_api_leads_csv"),
    path("api/leads/search/", views.api_leads_search, name="dashboard_api_leads_search"),
    path("api/leadlist/<int:list_id>/export/", views.api_leadlist_export, name="dashboard_api_leadlist_export"),
    path("api/inbox/accounts/", views.api_inbox_accounts, name="dashboard_api_inbox_accounts"),
    path("api/inbox/threads/", views.api_inbox_threads, name="dashboard_api_inbox_threads"),
    path("api/inbox/thread/<int:thread_id>/", views.api_inbox_thread, name="dashboard_api_inbox_thread"),
]
