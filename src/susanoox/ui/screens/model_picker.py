from __future__ import annotations

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from susanoox.config.settings import ModelName
from susanoox.models.catalog import MODELS, get_model


class ModelPickerScreen(ModalScreen[ModelName | None]):
    BINDINGS: ClassVar = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, *, current_model: ModelName) -> None:
        super().__init__()
        self._current_model = current_model

    def compose(self) -> ComposeResult:
        with Vertical(id="model-picker"):
            yield Static("Select a model", id="model-picker-title")
            for model in MODELS:
                state = "  ✓ active" if model.name == self._current_model else ""
                unavailable = "  · embeddings only" if not model.supports_chat else ""
                yield Button(
                    f"{model.name}{state}{unavailable}\n{model.description}",
                    id=f"model-{model.name}",
                    classes="model-option",
                    disabled=not model.supports_chat,
                )
            yield Static("Enter select  ·  Esc close", id="model-picker-help")

    @on(Button.Pressed, ".model-option")
    def select_model(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id is None:
            return
        model = get_model(button_id.removeprefix("model-"))
        if model is not None and model.supports_chat:
            self.dismiss(model.name)

    def action_cancel(self) -> None:
        self.dismiss(None)
