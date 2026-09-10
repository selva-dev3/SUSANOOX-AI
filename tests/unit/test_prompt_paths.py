from pathlib import Path

import pytest

from susanoox.ui.widgets.prompt import pasted_image_path


@pytest.mark.parametrize(
    "value", ["Explain screen.png", "code\n./screen.png", "screen.png", "See ./screen.png"]
)
def test_ordinary_paste_is_preserved(value: str) -> None:
    assert pasted_image_path(value) is None


@pytest.mark.parametrize("value", ["./screen.png", "'my screen.png'", '"my screen.png"'])
def test_explicit_image_paths(value: str) -> None:
    assert pasted_image_path(value) == Path(value.strip("'\""))


def test_absolute_path_with_spaces(tmp_path: Path) -> None:
    path = tmp_path / "my screen.png"
    assert pasted_image_path(str(path)) == path
