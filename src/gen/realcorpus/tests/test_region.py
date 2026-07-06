from __future__ import annotations

from gen.realcorpus.region import select_regions

SRC = """\
#include <x>
int add(int a, int b) {
    int s = a + b;
    return s;
}
// a comment with { braces } that must be ignored
int mul(int a, int b) {
    return a * b;
}
"""


def test_select_regions_finds_function_bodies():
    spans = select_regions(SRC, max_regions=8, min_lines=2)
    texts = [SRC[a:b] for a, b in spans]
    assert any("int s = a + b;" in t for t in texts)
    assert any("return a * b;" in t for t in texts)


def test_regions_are_within_bounds_and_ordered():
    spans = select_regions(SRC)
    assert all(0 <= a < b <= len(SRC) for a, b in spans)
    assert spans == sorted(spans)


def test_braces_in_comments_do_not_start_a_region():
    src = "// just { a comment }\nint f(){ return 0; }\n"
    spans = select_regions(src, min_lines=0)
    assert len(spans) == 1
    assert "return 0;" in src[spans[0][0]:spans[0][1]]
