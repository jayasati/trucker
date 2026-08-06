from django.urls import path

from routing.views import PlaceSuggestView, RouteView

urlpatterns = [
    path("route/", RouteView.as_view(), name="route"),
    path("places/", PlaceSuggestView.as_view(), name="places"),
]
