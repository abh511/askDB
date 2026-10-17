from askdb.charts import choose_chart


def test_text_and_number_gives_bar():
    chart = choose_chart(["category", "revenue"], [["health_beauty", 10.5], ["toys", 3.0]])
    assert chart == {"type": "bar", "x": "category", "y": "revenue"}


def test_date_column_gives_line():
    chart = choose_chart(["month", "orders"], [["2018-01-01", 10], ["2018-02-01", 12]])
    assert chart == {"type": "line", "x": "month", "y": "orders"}


def test_year_number_column_gives_line():
    chart = choose_chart(["year", "revenue"], [[2017, 1.0], [2018, 2.0]])
    assert chart == {"type": "line", "x": "year", "y": "revenue"}


def test_single_value_gives_table():
    assert choose_chart(["count"], [[99441]]) == {"type": "table"}


def test_two_numbers_gives_table():
    assert choose_chart(["a", "b"], [[1, 2], [3, 4]]) == {"type": "table"}


def test_three_columns_without_date_gives_table():
    rows = [["s1", 10.0, 3], ["s2", 8.0, 2]]
    assert choose_chart(["seller", "revenue", "orders"], rows) == {"type": "table"}
