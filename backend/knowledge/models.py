from django.db import models

from common.models import BaseModel


class KnowledgeModule(BaseModel):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    name = models.CharField(max_length=64)
    position = models.PositiveIntegerField(default=0)
    source_key = models.CharField(max_length=255, unique=True, null=True, blank=True, editable=False)
    source_hash = models.CharField(max_length=64, default="", blank=True, editable=False)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["position", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=models.Q(parent__isnull=True),
                                    name="knowledge_root_name_unique"),
            models.UniqueConstraint(fields=["parent", "name"], name="knowledge_sibling_name_unique"),
            models.CheckConstraint(condition=~models.Q(parent=models.F("id")),
                                   name="knowledge_module_not_self_parent"),
        ]


class KnowledgeDocument(BaseModel):
    module = models.ForeignKey(KnowledgeModule, on_delete=models.PROTECT, related_name="documents")
    title = models.CharField(max_length=160)
    markdown = models.TextField()
    position = models.PositiveIntegerField(default=0)
    source_key = models.CharField(max_length=255, unique=True, null=True, blank=True, editable=False)
    source_hash = models.CharField(max_length=64, default="", blank=True, editable=False)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["position", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["module", "title"], name="knowledge_document_module_title_unique"),
        ]
