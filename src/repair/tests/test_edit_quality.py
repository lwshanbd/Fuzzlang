from repair.eval.edit_quality import compute_edit_quality


def test_edit_quality_compares_prediction_with_input_and_gold() -> None:
    source = "int keep = 1;\nint value = missing;\n"
    gold = "int keep = 1;\nint value = 0;\n"

    quality = compute_edit_quality(source, gold, gold)

    assert quality["predicted_edit_size"] > 0
    assert quality["gold_edit_size"] == quality["predicted_edit_size"]
    assert quality["edit_size_ratio"] == 1.0
    assert quality["changed_original_lines"] == 1
    assert quality["changed_predicted_lines"] == 1
    assert quality["empty_repair"] is False
    assert quality["large_deletion"] is False
    assert quality["excessive_edit"] is False
    assert quality["degenerate"] is False


def test_edit_quality_flags_empty_large_deletion() -> None:
    source = "int first = 1;\nint second = 2;\nint third = 3;\n"
    gold = "int first = 1;\nint second = 0;\nint third = 3;\n"

    quality = compute_edit_quality(source, "", gold)

    assert quality["empty_repair"] is True
    assert quality["large_deletion"] is True
    assert quality["degenerate"] is True


def test_edit_quality_flags_edit_much_larger_than_gold() -> None:
    source = "int value = 1;\n" * 20
    gold = source.replace("1", "2", 1)
    predicted = "void unrelated();\n" * 20

    quality = compute_edit_quality(source, predicted, gold)

    assert quality["predicted_edit_size"] > 100
    assert quality["predicted_edit_size"] > 5 * quality["gold_edit_size"]
    assert quality["excessive_edit"] is True
    assert quality["degenerate"] is True


def test_edit_quality_flags_pure_line_deletion() -> None:
    source = "int first;\nint second;\n"
    gold = "int first;\nint second = 0;\n"
    predicted = "int first;\n"

    quality = compute_edit_quality(source, predicted, gold)

    assert quality["large_deletion"] is False
    assert quality["pure_line_deletion"] is True
    assert quality["degenerate"] is True


def test_edit_quality_does_not_flag_line_deletion_that_matches_gold() -> None:
    source = "int injected_error;\nint keep;\n"
    gold = "int keep;\n"

    quality = compute_edit_quality(source, gold, gold)

    assert quality["pure_line_deletion"] is False
    assert quality["degenerate"] is False
