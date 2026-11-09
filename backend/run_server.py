"""Точка входа для PyInstaller: backend без внешнего Python."""
import os
import uvicorn

from main import root_app

if __name__ == "__main__":
    uvicorn.run(
        root_app,
        host="127.0.0.1",
        port=int(os.environ.get("APP_PORT", "8000")),
        log_level="info",
    )
