# linkedin/admin.py
from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from chat.models import ChatMessage
from crm.models import Lead

from linkedin.leads import importer
from linkedin.models import ActionLog, Campaign, LeadList, LinkedInProfile, SearchKeyword, SiteConfig, Task


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "llm_provider", "ai_model", "llm_api_base")

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "booking_link", "is_freemium", "action_fraction")
    filter_horizontal = ("users",)


@admin.register(LinkedInProfile)
class LinkedInProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "linkedin_username", "active", "legal_accepted")
    list_filter = ("active",)
    raw_id_fields = ("user", "self_lead")


@admin.register(SearchKeyword)
class SearchKeywordAdmin(admin.ModelAdmin):
    list_display = ("keyword", "campaign", "used", "used_at")
    list_filter = ("used", "campaign")
    raw_id_fields = ("campaign",)


@admin.register(ActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ("action_type", "linkedin_profile", "campaign", "created_at")
    list_filter = ("action_type", "campaign")
    raw_id_fields = ("linkedin_profile", "campaign")
    date_hierarchy = "created_at"
    readonly_fields = ("linkedin_profile", "campaign", "action_type", "created_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("task_type", "status", "scheduled_at", "payload", "created_at")
    list_filter = ("task_type", "status")
    readonly_fields = (
        "task_type", "status", "scheduled_at", "payload",
        "created_at", "started_at", "completed_at",
    )
    date_hierarchy = "scheduled_at"


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("content_type", "object_id", "owner", "creation_date")
    list_filter = ("content_type", "owner")
    raw_id_fields = ("owner", "answer_to", "topic")
    date_hierarchy = "creation_date"
    readonly_fields = ("content_type", "object_id", "content", "owner", "creation_date")


class EnrichmentStatusFilter(admin.SimpleListFilter):
    """Filter Leads by whether they have been enriched (have an embedding)."""

    title = "enrichment status"
    parameter_name = "enriched"

    def lookups(self, request, model_admin):
        return (("yes", "Enriched"), ("no", "Not enriched"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(embedding__isnull=False)
        if self.value() == "no":
            return queryset.filter(embedding__isnull=True)
        return queryset


class LeadListCsvImportForm(forms.Form):
    name = forms.CharField(max_length=200)
    csv_file = forms.FileField()


@admin.register(LeadList)
class LeadListAdmin(admin.ModelAdmin):
    list_display = ("name", "source_type", "lead_count", "created_at", "archived_at", "view_leads")
    list_filter = ("source_type", "archived_at")
    search_fields = ("name",)
    readonly_fields = ("created_at", "archived_at", "view_leads")
    actions = ("archive_selected",)
    change_list_template = "admin/linkedin/leadlist/change_list.html"

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_lead_count=Count("leads"))

    @admin.display(description="leads", ordering="_lead_count")
    def lead_count(self, obj):
        return getattr(obj, "_lead_count", obj.leads.count())

    @admin.display(description="")
    def view_leads(self, obj):
        if not obj.pk:
            return ""
        url = reverse("admin:crm_lead_changelist") + f"?lead_list__id__exact={obj.pk}"
        count = getattr(obj, "_lead_count", obj.leads.count())
        return format_html('<a href="{}">View {} leads</a>', url, count)

    # Soft-delete only: never expose hard delete (spec §0.1).
    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Archive selected lead lists (soft-delete)")
    def archive_selected(self, request, queryset):
        count = 0
        for lead_list in queryset:
            lead_list.archive()
            count += 1
        self.message_user(request, f"Archived {count} lead list(s).", messages.SUCCESS)

    def get_urls(self):
        custom = [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_csv_view),
                name="linkedin_leadlist_import_csv",
            ),
        ]
        return custom + super().get_urls()

    def import_csv_view(self, request):
        if request.method == "POST":
            form = LeadListCsvImportForm(request.POST, request.FILES)
            if form.is_valid():
                lead_list = importer.create_lead_list(
                    name=form.cleaned_data["name"],
                    owner=request.user,
                    source_type=LeadList.SourceType.CSV,
                )
                lines = form.cleaned_data["csv_file"].read().decode("utf-8").splitlines()
                try:
                    result = importer.import_csv(lead_list, iter(lines))
                except ValueError as exc:
                    self.message_user(request, str(exc), messages.ERROR)
                    return redirect("admin:linkedin_leadlist_import_csv")
                self.message_user(
                    request,
                    f"Imported '{lead_list.name}': created={result['created']} "
                    f"skipped={result['skipped']} invalid={result['invalid']}",
                    messages.SUCCESS,
                )
                return redirect("admin:linkedin_leadlist_changelist")
        else:
            form = LeadListCsvImportForm()
        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "title": "Import leads from CSV",
            "opts": self.model._meta,
        }
        return render(request, "admin/linkedin/leadlist/import_csv.html", context)


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("public_identifier", "lead_list", "is_enriched", "disqualified", "creation_date")
    list_filter = ("lead_list", "disqualified", EnrichmentStatusFilter)
    search_fields = ("public_identifier", "linkedin_url")
    raw_id_fields = ("lead_list",)
    readonly_fields = ("creation_date", "update_date", "urn")

    @admin.display(boolean=True, description="enriched")
    def is_enriched(self, obj):
        return obj.embedding is not None

    def has_delete_permission(self, request, obj=None):
        return False
