"""Schichtwechsel web UI.

    streamlit run src/schichtwechsel/ui/app.py

On Streamlit Community Cloud the entry point is app/streamlit_app.py, which
calls main(). Data and the analyst run in the same process (backend.py).
Text comes from the locale files; data stays in canonical codes and is
translated for display only.
"""

from __future__ import annotations

import streamlit as st

from schichtwechsel.ui import pages
from schichtwechsel.ui.i18n import LANGUAGES, lang, t


def main() -> None:
    st.set_page_config(page_title="Schichtwechsel", layout="wide", initial_sidebar_state="expanded")
    with st.sidebar:
        st.markdown(f"### {t('app.title')}")
        st.caption(t("app.tagline"))
        st.session_state.lang = st.radio(
            t("app.language"),
            list(LANGUAGES),
            format_func=LANGUAGES.get,
            horizontal=True,
            index=list(LANGUAGES).index(lang()),
        )

    nav = [
        st.Page(pages.radar, title=t("nav.radar"), icon=":material/travel_explore:", default=True),
        st.Page(pages.offers, title=t("nav.offers"), icon=":material/redeem:", url_path="offers"),
        st.Page(
            pages.workforce,
            title=t("nav.workforce"),
            icon=":material/groups:",
            url_path="workforce",
        ),
        st.Page(
            pages.assistant, title=t("nav.assistant"), icon=":material/forum:", url_path="assistant"
        ),
    ]
    page = st.navigation(nav)
    try:
        page.run()
    except Exception as exc:  # data download or warehouse problems
        if "duckdb" not in type(exc).__module__ and "httpx" not in type(exc).__module__:
            raise
        st.error(t("app.data_down", error=type(exc).__name__))

    with st.sidebar:
        st.divider()
        st.caption(t("app.footer"))


if __name__ == "__main__":
    main()
