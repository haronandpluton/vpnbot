from app.config.settings import get_settings

settings = get_settings()

token = settings.bot_token

print("TOKEN RAW:", repr(token))
print("TOKEN START:", token[:10])
print("TOKEN LENGTH:", len(token))