from django.urls import path, re_path

from . import views

app_name = "knowledge"

urlpatterns = [
    path("", views.library, name="library"),
    path("search", views.search_documents, name="search"),
    re_path(r"^assets/(?P<digest>[a-f0-9]{64})\.(?P<extension>png|jpg|gif|webp)\Z",
            views.knowledge_asset, name="asset"),
    path("modules/<uuid:pk>", views.module_detail, name="module"),
    path("documents", views.add_document, name="add-document"),
    path("documents/<uuid:pk>", views.document_detail, name="document"),
]
