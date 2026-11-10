from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attachments", "0002_initial")]

    operations = [
        migrations.AddField(
            model_name="attachment",
            name="is_current",
            field=models.BooleanField(default=True, verbose_name="在当前附件列表中"),
        ),
    ]
