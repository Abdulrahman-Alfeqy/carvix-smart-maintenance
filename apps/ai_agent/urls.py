from django.urls import path

from . import views


app_name = "ai_agent"

urlpatterns = [
    path("chat/", views.chat_page, name="chat"),
    path("chat/message/", views.chat_message, name="chat-message"),
]
