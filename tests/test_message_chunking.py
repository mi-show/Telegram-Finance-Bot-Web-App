from app.handlers.common import _split_message_chunks


def test_split_message_chunks_respects_limit_for_multiline_text():
    text = "\n".join(f"{i:04d} some-long-category-name amount 123.45 UAH" for i in range(350))

    chunks = _split_message_chunks(text, chunk_size=220)

    assert len(chunks) > 1
    assert all(len(chunk) <= 220 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_split_message_chunks_handles_single_very_long_line():
    text = "A" * 5000

    chunks = _split_message_chunks(text, chunk_size=1000)

    assert len(chunks) == 5
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert "".join(chunks) == text
