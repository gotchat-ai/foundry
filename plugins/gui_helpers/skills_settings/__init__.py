from .store import get_skill_settings, resolve_skill_setting


def install(app):
    from .routes import install as _install
    return _install(app)
