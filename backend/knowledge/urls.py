from django.urls import path, re_path

from . import views, history, transfer

app_name = "knowledge"

urlpatterns = [
    path("", views.library, name="library"),
    path("search", views.search_documents, name="search"),
    path("assets", transfer.upload_image, name="upload-image"),
    path("import", transfer.import_archive, name="import-archive"),
    path("modules/<uuid:pk>/export", transfer.export_space, name="export-space"),
    path("trash", history.trash, name="trash"),
    path("trash/<uuid:pk>/restore", history.restore_document, name="restore-document"),
    path("documents/<uuid:pk>/history", history.document_history, name="history"),
    path("documents/<uuid:pk>/history/<uuid:revision_id>", history.history_revision, name="history-revision"),
    re_path(r"^assets/(?P<digest>[a-f0-9]{64})\.(?P<extension>png|jpg|gif|webp)\Z",
            views.knowledge_asset, name="asset"),
    path("modules/<uuid:pk>", views.module_detail, name="module"),
    path("documents", views.add_document, name="add-document"),
    path("documents/<uuid:pk>", views.document_detail, name="document"),
]
