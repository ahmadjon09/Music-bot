"""The public page must expose nothing: no inputs, no buttons, no data."""


def test_public_page_is_bare():
    from src.web.gradio_ui import _PAGE, build_gradio

    demo = build_gradio()
    kinds = {type(block).__name__ for block in demo.blocks.values()}
    forbidden = {"Button", "Textbox", "TextArea", "Dropdown", "Slider",
                 "Checkbox", "Radio", "File", "Image", "Audio"}
    assert not (kinds & forbidden), f"interactive components leaked: {kinds & forbidden}"
    assert "In deployment" in _PAGE
