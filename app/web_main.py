import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.web.app:app",
        host=settings.webapp_host,
        port=settings.webapp_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
