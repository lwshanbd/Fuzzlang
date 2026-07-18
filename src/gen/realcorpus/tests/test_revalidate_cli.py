from pathlib import Path

import gen.realcorpus.run_revalidate_replay as cli


def test_load_many_combines_every_base_file(monkeypatch):
    rows = {Path("base-a.jsonl"): ["a"], Path("base-b.jsonl"): ["b", "c"]}
    monkeypatch.setattr(cli, "_load", rows.__getitem__)

    assert cli._load_many(list(rows)) == ["a", "b", "c"]
