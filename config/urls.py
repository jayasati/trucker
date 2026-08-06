from django.contrib import admin
from django.urls import include, path

from routing.views import (
    AnalyticsPageView,
    DashboardPageView,
    FuelDirectoryPageView,
    RoutePlannerPageView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RoutePlannerPageView.as_view(), name="route-planner"),
    path("dashboard/", DashboardPageView.as_view(), name="dashboard"),
    path("fuel/", FuelDirectoryPageView.as_view(), name="fuel-directory"),
    path("analytics/", AnalyticsPageView.as_view(), name="analytics"),
    path("api/", include("routing.urls")),
]
