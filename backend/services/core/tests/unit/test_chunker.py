from openinterview_core.domain.projects.chunker import CodeChunker, DocChunker


PY = '''\
import os

def foo(a, b):
    return a + b


class Bar:
    def baz(self):
        return 1
'''


def test_python_chunker_splits_by_symbol() -> None:
    chunks = CodeChunker().chunk(rel_path="m.py", language="python", text=PY)
    symbols = [c.symbol for c in chunks if c.symbol]
    assert "foo" in symbols
    assert "Bar" in symbols
    # All chunks have valid line ranges
    for c in chunks:
        assert c.start_line >= 1 and c.end_line >= c.start_line


def test_window_chunker_for_unknown_language() -> None:
    text = "\n".join([f"line {i}" for i in range(500)])
    chunks = CodeChunker().chunk(rel_path="big.go", language="go", text=text)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.symbol is None


def test_doc_chunker_splits_by_heading() -> None:
    md = "# Top\nintro\n\n## A\nbody-a\n\n## B\nbody-b\n"
    chunks = DocChunker().chunk(rel_path="r.md", text=md)
    sections = [c.section for c in chunks if c.section]
    assert "Top" in sections
    assert "A" in sections
    assert "B" in sections
