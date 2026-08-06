from django.contrib import admin
from django.urls import include, path

from routing.views import DashboardPageView, RoutePlannerPageView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RoutePlannerPageView.as_view(), name="route-planner"),
    path("dashboard/", DashboardPageView.as_view(), name="dashboard"),
    path("api/", include("routing.urls")),
]
