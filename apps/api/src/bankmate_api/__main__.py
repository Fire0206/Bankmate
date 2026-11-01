import uvicorn

from bankmate_api.config import get_settings

settings = get_settings()

uvicorn.run(
    "bankmate_api.main:app",
    host=settings.api_host,
    port=settings.api_port,
    reload=settings.environment == "development",
)
