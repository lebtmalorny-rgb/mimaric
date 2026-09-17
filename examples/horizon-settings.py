# /etc/kolla/config/horizon/_9999-custom-settings.py
# Loaded by Horizon after HORIZON_CONFIG has been defined.
ALLOW_USERS_CHANGE_EXPIRED_PASSWORD = True
HORIZON_CONFIG['password_validator'] = {
    'regex': '.*',
    'help_text': 'Требования к паролю проверяются сервером Keystone.',
}
