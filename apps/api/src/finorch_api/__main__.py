import uvicorn

from finorch_api.config import get_settings

settings = get_settings()

uvicorn.run(
    "finorch_api.main:app",
    host=settings.api_host,
    port=settings.api_port,
    reload=settings.environment == "development",
)
