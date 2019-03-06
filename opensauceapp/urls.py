from django.urls import path
from django.contrib import admin
from django.views.generic.base import RedirectView

from . import views
from django.contrib.auth import views as reg_views

urlpatterns = [
    path('', views.index, name='index'),
    path(r'lobby/<lobby_name>/', views.lobby, name='lobby'),
    path(r'lobby/', RedirectView.as_view(url='/'), name='lobbyEmpty'),
    path(r'lobbies_list/', views.lobbies_list, name='lobbies_list'),

    path(r'reports/', views.reports, name='reports'),

    # Auth. System
    path(r'login/', reg_views.LoginView.as_view(), name='login'),
    path(r'logout/', reg_views.LogoutView.as_view(), name='logout'),
]
