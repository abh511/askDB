import pytest

from askdb.guard import GuardError, check_sql

TABLES = {"orders", "order_items", "customers", "products", "category_translation"}


def test_select_allowed():
    result = check_sql("SELECT order_id FROM orders LIMIT 10", TABLES)
    assert result.sql == "SELECT order_id FROM orders LIMIT 10"
    assert result.tables == ["orders"]


def test_drop_blocked():
    with pytest.raises(GuardError, match="Only SELECT"):
        check_sql("DROP TABLE orders", TABLES)


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "UPDATE orders SET order_status = 'x'",
    "INSERT INTO orders (order_id) VALUES ('x')",
    "TRUNCATE orders",
    "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE x (a INT)",
    "GRANT SELECT ON orders TO someone",
    "SET statement_timeout = 0",
])
def test_write_and_admin_statements_blocked(sql):
    with pytest.raises(GuardError):
        check_sql(sql, TABLES)


def test_multiple_statements_blocked():
    with pytest.raises(GuardError, match="Exactly one statement"):
        check_sql("SELECT 1 FROM orders; DROP TABLE orders", TABLES)


def test_delete_hidden_in_cte_blocked():
    with pytest.raises(GuardError, match="DELETE"):
        check_sql("WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d", TABLES)


def test_select_into_blocked():
    with pytest.raises(GuardError, match="INTO"):
        check_sql("SELECT * INTO copy_of_orders FROM orders", TABLES)


def test_unknown_table_blocked():
    with pytest.raises(GuardError, match="Unknown table"):
        check_sql("SELECT * FROM users", TABLES)


def test_system_catalog_blocked():
    with pytest.raises(GuardError, match="pg_catalog.pg_user"):
        check_sql("SELECT * FROM pg_catalog.pg_user", TABLES)


def test_cte_names_are_not_unknown_tables():
    result = check_sql("WITH t AS (SELECT order_id FROM orders) SELECT * FROM t", TABLES)
    assert result.tables == ["orders"]


def test_column_named_like_keyword_is_fine():
    # a regex for "DELETE"/"UPDATE" would wrongly block this
    check_sql("SELECT order_delivered_customer_date AS updated FROM orders", TABLES)


def test_limit_added_when_missing():
    result = check_sql("SELECT order_id FROM orders", TABLES, row_limit=500)
    assert result.sql.endswith("LIMIT 500")


def test_big_limit_lowered():
    result = check_sql("SELECT order_id FROM orders LIMIT 100000", TABLES, row_limit=500)
    assert result.sql.endswith("LIMIT 500")


def test_small_limit_kept_and_semicolon_stripped():
    result = check_sql("SELECT order_id FROM orders LIMIT 5;", TABLES)
    assert result.sql == "SELECT order_id FROM orders LIMIT 5"


def test_union_allowed_and_limited():
    result = check_sql("SELECT customer_id FROM orders UNION SELECT customer_id FROM customers", TABLES)
    assert result.sql.endswith("LIMIT 500")


@pytest.mark.parametrize("sql", ["", "   ", "SELEC order_id FROM orders WHERE ((("])
def test_empty_or_garbage_blocked(sql):
    with pytest.raises(GuardError):
        check_sql(sql, TABLES)
