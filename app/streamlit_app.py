"""Streamlit UI: question box -> SQL, result table, Plotly chart, one-line answer.

The UI only talks to the API; it has no pipeline logic of its own.
"""
import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

EXAMPLES = [
    "Which 5 product categories earned the most revenue in 2017?",
    "How many orders were placed each month in 2018?",
    "What share of delivered orders arrived after the estimated delivery date?",
    "Which 10 states have the most customers?",
]

st.set_page_config(page_title="AskDB", page_icon="📊", layout="wide")
st.title("AskDB")
st.caption("Ask a business question about the Olist Brazilian e-commerce data (2016–2018). "
           "AskDB writes the SQL, runs it read-only, and answers with a table, a chart and one sentence.")

if "question" not in st.session_state:
    st.session_state.question = ""

with st.sidebar:
    st.subheader("Try an example")
    for example in EXAMPLES:
        if st.button(example, width="stretch"):
            st.session_state.question = example

with st.form("ask"):
    question = st.text_input("Question", key="question",
                             placeholder="Which 5 product categories earned the most revenue in 2017?")
    submitted = st.form_submit_button("Ask", type="primary")


def show_chart(chart: dict, df: pd.DataFrame) -> None:
    kind, x, y = chart.get("type"), chart.get("x"), chart.get("y")
    if kind == "bar":
        st.plotly_chart(px.bar(df, x=x, y=y), width="stretch")
    elif kind == "line":
        st.plotly_chart(px.line(df.sort_values(x), x=x, y=y, markers=True), width="stretch")


if submitted and question.strip():
    try:
        with st.spinner("Writing and running SQL..."):
            resp = requests.post(f"{API_URL}/ask", json={"question": question}, timeout=120)
            resp.raise_for_status()
            data = resp.json()
    except requests.RequestException as exc:
        st.error(f"Could not reach the AskDB API at {API_URL}: {exc}")
        st.stop()

    status = data["status"]
    if status == "ok":
        st.success(data["answer"] or "Done.")
    elif status == "blocked":
        st.warning(f"Query blocked by the safety guard: {data['reason']}")
    else:
        st.error(f"Could not answer: {data['reason']}")

    if data.get("sql"):
        st.code(data["sql"], language="sql")

    if status == "ok":
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        left, right = st.columns([1, 1])
        with left:
            st.dataframe(df, width="stretch", hide_index=True)
        with right:
            show_chart(data["chart"], df)
    st.caption(f"{data['attempts']} attempt(s) · {data['latency_ms']:,} ms")
