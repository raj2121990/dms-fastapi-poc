from pathlib import Path
from utils import extract_text_from_file


def test_extract_text_from_txt(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("Hello testing world\nLine two", encoding="utf-8")

    text = extract_text_from_file(str(p), "text/plain")
    assert "Hello testing world" in text
    assert "Line two" in text
