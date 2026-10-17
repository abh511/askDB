from eval.compare import results_match


def test_same_rows_different_order_match():
    assert results_match([["a", 1], ["b", 2]], [["b", 2], ["a", 1]], ordered=False)


def test_ordered_question_respects_order():
    assert not results_match([["a", 2], ["b", 1]], [["b", 1], ["a", 2]], ordered=True)
    assert results_match([["a", 2], ["b", 1]], [["a", 2], ["b", 1]], ordered=True)


def test_decimals_rounded():
    assert results_match([[4.0866]], [[4.09]])
    assert not results_match([[4.08]], [[4.09]])


def test_int_and_float_equal():
    assert results_match([[3]], [[3.0]])


def test_column_names_ignored():
    # results_match only sees rows; column names never reach it
    assert results_match([["SP", 10]], [["SP", 10]])


def test_column_order_ignored():
    assert results_match([["health_beauty", 1.5]], [[1.5, "health_beauty"]])


def test_duplicates_count():
    assert not results_match([["a"], ["a"]], [["a"]])


def test_extra_column_is_wrong():
    assert not results_match([["SP", 10]], [["SP", 10, 99]])


def test_missing_row_is_wrong():
    assert not results_match([["a"], ["b"]], [["a"]])


def test_none_values():
    assert results_match([[None, 1]], [[None, 1]])


def test_midnight_timestamp_equals_date():
    assert results_match([["2018-01-01T00:00:00"]], [["2018-01-01"]])
    assert not results_match([["2018-01-01T10:00:00"]], [["2018-01-01"]])
