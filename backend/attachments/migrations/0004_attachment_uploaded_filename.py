from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attachments", "0003_attachment_is_current")]

    operations = [
        migrations.AddField(
            model_name="attachment",
            name="uploaded_filename",
            field=models.CharField("上传时的文件名", max_length=255, blank=True, default=""),
        ),
    ]
