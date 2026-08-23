# created by thy.nguyen for gotchat.ai foundry
# license Apache 2.0
"""Compatibility entrypoint for the refactored llmloader2 app."""

from app_main.main import app, create_app, load_settings, main

__all__ = ["app", "create_app", "load_settings", "main"]


if __name__ == "__main__":
    main()
