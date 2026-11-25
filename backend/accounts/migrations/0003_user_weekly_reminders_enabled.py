from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_session_version_alter_user_account_status_and_more")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="weekly_reminders_enabled",
            field=models.BooleanField(default=True, verbose_name="周报定时邮件提醒"),
        ),
    ]
