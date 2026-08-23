from typing import Any, Callable


class ModelRuntimeState:
    """Owns active model replacement and related thinking-model alignment."""

    def __init__(
        self,
        *,
        model_getter: Callable[[], Any],
        model_setter: Callable[[Any], None],
        thinking_model_setter: Callable[[Any], None],
        backend_type_getter: Callable[[], str],
        dispose_model: Callable[[Any], None],
    ) -> None:
        self._model_getter = model_getter
        self._model_setter = model_setter
        self._thinking_model_setter = thinking_model_setter
        self._backend_type_getter = backend_type_getter
        self._dispose_model = dispose_model

    def get_current_model(self) -> Any:
        return self._model_getter()

    def set_current_model(self, new_model: Any) -> None:
        old_model = self._model_getter()
        try:
            print(
                f"[set_current_model] old={old_model.__class__.__name__ if old_model is not None else 'None'} "
                f"new={new_model.__class__.__name__ if new_model is not None else 'None'} "
                f"old_path={getattr(old_model, 'model_path', None) if old_model is not None else None} "
                f"new_path={getattr(new_model, 'model_path', None) if new_model is not None else None}",
                flush=True,
            )
        except Exception:
            pass

        self._model_setter(new_model)
        if old_model is not None and old_model is not new_model:
            try:
                try:
                    print(
                        f"[set_current_model] disposing old={old_model.__class__.__name__} "
                        f"path={getattr(old_model, 'model_path', None)}",
                        flush=True,
                    )
                except Exception:
                    pass
                self._dispose_model(old_model)
            except Exception:
                pass

        try:
            if self._backend_type_getter() in ("hf", "hf_assist"):
                self._thinking_model_setter(new_model)
        except Exception:
            pass
