"""Create development secrets without overwriting an existing environment."""
import base64
import os
import secrets

fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as out:
    out.write('ADMIN_KEY=' + secrets.token_urlsafe(40) + '\n')
    out.write('SIGNING_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode() + '\n')
print('Created .env with fresh local development credentials. Do not commit it.')
