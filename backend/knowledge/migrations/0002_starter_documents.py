from django.db import migrations


STARTER_CONTENT = {
    "周报与组会": [
        ("从上传到提交", """这是一份周报系统使用说明，供成员第一次提交周报时参考。

## 准备周报

在文件里写清楚本周完成了什么、结论依据是什么、还有哪些待确认的问题。需要 AI 提取附件内容时，使用带有文字层的 PDF 或可转换的办公文档。

## 提交步骤

1. 从首页进入 **提交周报**，检查页面显示的周次。
2. 上传文件，打开预览，核对标题、表格和页序。
3. 确认预览无误后提交。回到工作台查看提交状态。

## 更正已交的周报

打开本周周报，选择 **更正周报**，替换需要更新的文件并再次提交。再次提交会生成新版本。
"""),
        ("在组会上逐篇展示原文", """管理员可用这份系统使用说明准备组会。

1. 打开 **团队周报**，选择需要汇报的周次。
2. 检查已提交名单，点击 **组会展示**。
3. 在页面最左侧点成员姓名。右侧展示该成员这一版周报的原文。
4. 用键盘的左右方向键切换成员，文档有多页时向下滚动。

如果名单为空，先检查所选周次，再确认成员是否已经提交。已上传但仍在草稿中的文件需要完成提交后才能展示。
"""),
    ],
    "研究记录": [
        ("可复查的实验记录", """下面是一份通用实验记录模板，可按课题需要调整。

| 记录项 | 应写下的信息 |
| --- | --- |
| 问题 | 本次实验要验证哪个判断 |
| 输入 | 数据批次、样本范围和筛选条件 |
| 方法 | 程序版本、关键参数和对照组 |
| 结果 | 指标的数值、单位和计算口径 |

## 记录观察

用一两句话概括观察到的变化，再给出能复查这一变化的图、表或文件位置。保留失败样本的编号，便于组会上回到原始记录。

## 写下下一步

把待验证的问题和准备采取的动作配成一对。例如，若某个批次误差上升，可先固定参数重跑该批次，并核对输入数据的处理记录。
"""),
    ],
    "知识库维护": [
        ("编写和导入 Markdown 文档", """本页是组内知识库的通用使用说明。

## 按主题归档

每个模块对应一个主题。先选模块，再从目录中点文章。管理员可建立模块，也可以在编辑文档时调整其所属模块。

## 新增文章

点击 **新建文档**，填写标题和 Markdown 正文。已有文件时可以选择 **导入 .md**，核对预览后保存。成员刷新知识库即可读到更新。

## 排版示例

使用二级标题划分章节，用有序列表记录操作顺序，代码或命令用反引号包裹。例如：

```markdown
## 复现步骤

1. 记录输入数据版本。
2. 执行 `python run.py`。
3. 保存结果并写下结论。
```
"""),
    ],
}


def seed_documents(apps, schema_editor):
    Module = apps.get_model("knowledge", "KnowledgeModule")
    Document = apps.get_model("knowledge", "KnowledgeDocument")
    alias = schema_editor.connection.alias
    for name, articles in STARTER_CONTENT.items():
        module, _ = Module.objects.using(alias).get_or_create(name=name)
        for title, markdown in articles:
            Document.objects.using(alias).get_or_create(
                module=module, title=title, defaults={"markdown": markdown})


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0001_initial")]
    operations = [migrations.RunPython(seed_documents, migrations.RunPython.noop)]
