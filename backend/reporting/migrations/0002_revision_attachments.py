from django.db import migrations, models


def restore_known_links(apps, schema_editor):
    Revision = apps.get_model("reporting", "WeeklyReportRevision")
    Attachment = apps.get_model("attachments", "Attachment")
    db = schema_editor.connection.alias
    for revision in Revision.objects.using(db).select_related("report").iterator():
        ids = set()
        if revision.confirmed_pdf_attachment_id:
            ids.add(revision.confirmed_pdf_attachment_id)
        # 旧版仅记录了每次提交的主 PDF。当前版本还可从周报找回提交时已有的附件。
        if revision.report.current_revision_id == revision.pk:
            ids.update(Attachment.objects.using(db).filter(
                report_id=revision.report_id, created_at__lte=revision.submitted_at,
            ).values_list("pk", flat=True))
        if ids:
            revision.attachments.add(*ids)


class Migration(migrations.Migration):
    dependencies = [
        ("attachments", "0003_attachment_is_current"),
        ("reporting", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="weeklyreportrevision",
            name="attachments",
            field=models.ManyToManyField(blank=True, related_name="submitted_revisions",
                                         to="attachments.attachment", verbose_name="提交时的附件"),
        ),
        migrations.RunPython(restore_known_links, migrations.RunPython.noop),
    ]
