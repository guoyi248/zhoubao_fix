from django.db import migrations

from system_config.credentials import CredentialUnavailable, decrypt_legacy_for_migration, seal
from system_config.integrations import KEYS, SECRET_FIELD, defaults, destination


def bind_credentials(apps, schema_editor):
    settings_table = apps.get_model("system_config", "SystemSetting").objects.using(schema_editor.connection.alias)
    for section, key in KEYS.items():
        row = settings_table.select_for_update().filter(key=key).first()
        if row is None:
            continue
        record = row.value
        overrides = record.get("values", {})
        field = SECRET_FIELD[section]
        previous = overrides.get(field)
        if not previous:
            continue
        if isinstance(previous, str):
            # Early configurations stored a bare credential in the section's values.
            cleartext = previous
            address = destination(section, {**defaults(section), **overrides})
        elif isinstance(previous, dict):
            token = previous.get("token")
            address = previous.get("destination")
            if not isinstance(address, list) or not isinstance(token, str):
                raise CredentialUnavailable()
            if token.startswith("v2:"):
                continue
            cleartext = decrypt_legacy_for_migration(token)
        else:
            raise CredentialUnavailable()
        overrides[field] = {"destination": address, "token": seal(cleartext, section=section, destination=address)}
        row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [("system_config", "0001_initial")]
    operations = [migrations.RunPython(bind_credentials)]
