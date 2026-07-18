from __future__ import annotations

from gen.realcorpus.region import select_regions, select_typed_regions

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


def test_typed_regions_include_functions_records_and_preprocessor():
    src = """\
#define FLAG 1
struct S {
  int x;
};
int f() {
  return FLAG;
}
"""
    regions = select_typed_regions(src, max_regions=10, min_lines=0)
    kinds = {r.kind for r in regions}
    assert {"function", "record", "preprocessor"} <= kinds


def test_typed_regions_round_robin_kinds_under_a_small_cap():
    src = "#define X 1\nstruct S { int x; };\nint f() { return X; }\n"
    regions = select_typed_regions(src, max_regions=3, min_lines=0)
    assert {r.kind for r in regions} == {"function", "record", "preprocessor"}
