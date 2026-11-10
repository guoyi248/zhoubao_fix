from importlib import import_module

from django.db import migrations
from django.utils import timezone


GUIDE = """## 查找文档

打开组内知识库，选择空间，展开目录，再点击文档标题。查看正文上方的路径可以回到上级目录。也可以用搜索框按标题或正文查找文章。

## 编写和导入

管理员可以在空间里新建目录，在相应位置添加文档。已有笔记可以导入 UTF-8 编码的 `.md` 或 `.markdown` 文件，核对预览后保存。组内成员登录后即可阅读，也可以用浏览器地址直接分享当前文档。

## Markdown 排版

文档标题单独填写。正文用二级标题划分章节，用列表说明步骤，用表格对照参数。代码块第一行可以标注语言。

```python
def coverage(area, total):
    return area / total
```

| 参数 | 含义 |
| --- | --- |
| area | 有效覆盖面积 |
| total | 研究区总面积 |
"""


def group_guides(apps, schema_editor):
    modules = apps.get_model("knowledge", "KnowledgeModule").objects.using(schema_editor.connection.alias)
    documents = apps.get_model("knowledge", "KnowledgeDocument").objects.using(schema_editor.connection.alias)
    original = import_module("knowledge.migrations.0002_starter_documents").STARTER_CONTENT
    untouched = []
    for index, (name, articles) in enumerate(original.items()):
        folder = modules.filter(name=name, parent=None, version=1).first()
        if folder is None or modules.filter(parent=folder).exists():
            continue
        content = documents.filter(module=folder).values_list("title", "markdown", "version")
        if set(content) == {(title, body, 1) for title, body in articles}:
            untouched.append((index, folder))

    # Leave custom folders and any existing space with the same name in place.
    if untouched and not modules.filter(parent=None, name="组内指南").exists():
        space = modules.create(name="组内指南")
        for index, folder in untouched:
            modules.filter(pk=folder.pk).update(parent=space, position=index,
                                                version=2, updated_at=timezone.now())

    title, old_text = original["知识库维护"][0]
    documents.filter(module__name="知识库维护", module__source_key__isnull=True, title=title,
                     markdown=old_text, version=1).update(markdown=GUIDE, version=2, updated_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0003_knowledge_hierarchy")]
    operations = [migrations.RunPython(group_guides, migrations.RunPython.noop)]
