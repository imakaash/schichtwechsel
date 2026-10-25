"""The four pages of the web UI. The shell around them is app.py."""

from __future__ import annotations

import hmac

import pandas as pd
import streamlit as st

from schichtwechsel.ui import charts
from schichtwechsel.ui.backend import LimitReached, ask, dataset, new_conversation, secret
from schichtwechsel.ui.i18n import label, lang, number, percent, t

AVATAR = {"user": ":material/person:", "assistant": ":material/query_stats:"}


def mode() -> str:
    theme = getattr(st.context, "theme", None)
    return getattr(theme, "type", None) or "light"


def show(fig) -> None:
    if fig is not None:
        st.plotly_chart(fig, theme=None, use_container_width=True, config={"displayModeBar": False})


def table(frame: pd.DataFrame) -> None:
    with st.expander(t("common.table")):
        st.dataframe(frame, hide_index=True, use_container_width=True)


def heading(title: str, help_text: str | None = None) -> None:
    st.subheader(title)
    if help_text:
        st.caption(help_text)


# pages ------------------------------------------------------------------


def radar() -> None:
    meta = dataset("meta").iloc[0]
    st.title(t("radar.title"))
    st.caption(f"{t('radar.intro')} {t('common.as_of', date=meta['snapshot_date'])}")

    pressure = dataset("pressure")
    scale = dataset("employer_scale")
    coverage = dataset("coverage")
    sales = pressure[pressure["role_family"] == "store_sales"]
    top_region = sales.sort_values("pressure_index", ascending=False).iloc[0]
    top_store = (
        scale[scale["competitor"] != "mueller"]
        .sort_values("postings_per_100_stores", ascending=False)
        .iloc[0]
    )

    a, b, c = st.columns(3)
    a.metric(t("radar.tile_open"), number(meta["open_postings"]))
    b.metric(
        t("radar.tile_pressure"),
        label("region", top_region["region"]),
        f"{t('radar.hover_index')} {number(top_region['pressure_index'])}",
        delta_color="off",
        delta_arrow="off",
    )
    c.metric(
        t("radar.tile_per_store"),
        label("competitor", top_store["competitor"]),
        f"{number(top_store['postings_per_100_stores'])} {t('common.per_100_stores')}",
        delta_color="off",
        delta_arrow="off",
    )

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        heading(t("radar.map_title"), t("radar.map_help"))
        roles = ["store_sales", "store_management", "logistics"]
        role = st.segmented_control(
            t("radar.role"),
            roles,
            default="store_sales",
            format_func=lambda r: label("role", r),
            label_visibility="collapsed",
        )
        part = pressure[pressure["role_family"] == (role or "store_sales")]

        def hover(region, row):
            return (
                f"<b>{label('region', region)}</b><br>"
                f"{t('radar.hover_index')}: {number(row['pressure_index'], 1)}<br>"
                f"{number(row['per_100k_inhabitants'], 1)} {t('radar.hover_per_100k')}<br>"
                f"{t('radar.hover_drugstore')}: {number(row['drugstore_postings'])} · "
                f"{t('radar.hover_grocery')}: {number(row['grocery_postings'])}"
            )

        show(charts.tile_map(part, t("region_abbr"), hover, mode(), lang()))
        missing = int(coverage["without_location"].sum())
        st.caption(t("radar.no_location", n=number(missing)))
        table(part[["region_name", "pressure_index", "per_100k_inhabitants", "open_postings"]])

    with right:
        heading(t("radar.per_store_title"), t("radar.per_store_help"))
        names = [label("competitor", c) for c in scale["competitor"]]
        values = scale["postings_per_100_stores"].tolist()
        hover = [
            f"<b>{n}</b><br>{number(v, 1)} {t('common.per_100_stores')}<br>"
            f"{number(o)} / {number(s)}"
            for n, v, o, s in zip(
                names, values, scale["open_postings"], scale["stores_de"], strict=True
            )
        ]
        show(charts.hbar(names, values, [number(v) for v in values], hover, mode(), lang()))

        heading(t("radar.minijob_title"), t("radar.minijob_help"))
        wt = dataset("working_time")
        wt = wt[wt["postings"] >= 20]
        names = [label("competitor", c) for c in wt["competitor"]]
        shares = wt["share_minijob"].tolist()
        hover = [
            f"<b>{n}</b><br>{percent(s, 1)} · {t('common.n', n=number(p))}"
            for n, s, p in zip(names, shares, wt["postings"], strict=True)
        ]
        show(charts.hbar(names, shares, [percent(s) for s in shares], hover, mode(), lang()))

    st.caption(t("common.source_ba"))


def offers() -> None:
    st.title(t("offers.title"))
    st.caption(t("offers.intro"))
    benefits = dataset("benefits")
    benefits = benefits[benefits["competitor"] != "mueller"]  # two postings, not comparable

    heading(t("offers.benefits_title"), t("offers.benefits_help"))
    n_by = benefits.groupby("competitor")["postings_with_text"].first()

    def hover(benefit, competitor):
        row = benefits[(benefits["benefit"] == benefit) & (benefits["competitor"] == competitor)]
        if row.empty:
            return ""
        r = row.iloc[0]
        counts = f"{number(r['postings_mentioning'])} / {number(r['postings_with_text'])}"
        return (
            f"<b>{label('competitor', competitor)}</b> · {label('benefit', benefit)}<br>"
            f"{percent(r['share'])} ({counts})"
        )

    show(
        charts.heatmap(
            benefits,
            "competitor",
            "benefit",
            "share",
            t("competitor"),
            t("benefit"),
            hover,
            mode(),
            lang(),
        )
    )
    st.caption(t("offers.coverage", n=number(int(n_by.sum()))))

    left, right = st.columns(2, gap="large")
    pay = dataset("pay")
    regular = pay[(pay["track"] == "regular") & (pay["competitor"] != "mueller")]
    with left:
        heading(t("offers.pay_title"), t("offers.pay_help"))
        names = [label("competitor", c) for c in regular["competitor"]]
        shares = regular["share_pay_stated"].tolist()
        hover = [
            f"<b>{n}</b><br>{percent(s)} · {t('common.n', n=number(k))}"
            for n, s, k in zip(names, shares, regular["postings_with_text"], strict=True)
        ]
        show(charts.hbar(names, shares, [percent(s) for s in shares], hover, mode(), lang()))
    with right:
        heading(t("offers.median_title"), t("offers.median_help"))
        enough = regular[regular["hourly_n"] >= 10]
        names = [label("competitor", c) for c in enough["competitor"]]
        values = enough["median_hourly_pay"].tolist()
        hover = [
            f"<b>{n}</b><br>{number(v, 2)} € · {t('common.n', n=number(k))}"
            for n, v, k in zip(names, values, enough["hourly_n"], strict=True)
        ]
        if values:
            show(
                charts.hbar(
                    names, values, [f"{number(v, 2)} €" for v in values], hover, mode(), lang()
                )
            )
        few = [label("competitor", c) for c in regular[regular["hourly_n"] < 10]["competitor"]]
        if few:
            st.caption(f"{', '.join(few)}: {t('offers.few')}")
    table(regular)
    st.caption(t("common.source_ba"))


def workforce() -> None:
    st.title(t("workforce.title"))
    st.badge(t("common.synthetic"), color="orange")
    st.caption(t("workforce.intro"))

    outlook = dataset("attrition_outlook")
    quality = dataset("model_quality")
    auc = quality[(quality["model"] == "attrition_logistic") & (quality["metric"] == "roc_auc")]

    a, b, c = st.columns(3)
    a.metric(t("workforce.tile_headcount"), number(outlook["headcount"].sum()))
    b.metric(t("workforce.tile_leavers"), number(outlook["expected_leavers_3m"].sum()))
    c.metric(t("workforce.tile_auc"), number(auc["value"].iloc[0], 2) if not auc.empty else "–")

    left, right = st.columns(2, gap="large")
    with left:
        heading(t("workforce.outlook_title"), t("workforce.outlook_help"))
        by_region = outlook.groupby("region", as_index=False)[
            ["expected_leavers_3m", "headcount"]
        ].sum()
        names = [label("region", r) for r in by_region["region"]]
        values = by_region["expected_leavers_3m"].tolist()
        hover = [
            f"<b>{n}</b><br>{number(v, 1)} / {number(h)}"
            for n, v, h in zip(names, values, by_region["headcount"], strict=True)
        ]
        show(charts.hbar(names, values, [number(v) for v in values], hover, mode(), lang()))
    with right:
        heading(t("workforce.drivers_title"), t("workforce.drivers_help"))
        drivers = dataset("attrition_drivers").head(8)
        names = [label("driver", f) for f in drivers["feature"]]
        values = drivers["mean_abs_shap"].tolist()
        show(charts.hbar(names, values, [number(v, 2) for v in values], names, mode(), lang()))

        heading(t("workforce.ttf_title"), t("workforce.ttf_help"))
        ttf = dataset("time_to_fill")
        openings = ["sales_associate", "minijob", "deputy_manager", "store_manager"]
        opening = st.segmented_control(
            t("workforce.opening"),
            openings,
            default="sales_associate",
            format_func=lambda o: label("opening", o),
            label_visibility="collapsed",
        )
        part = ttf[ttf["opening"] == (opening or "sales_associate")]
        names = [label("region", r) for r in part["region"]]
        days = t("common.days")
        hover = [
            f"<b>{n}</b><br>Median {number(m)} {days} · P80 {number(p)} {days}"
            for n, m, p in zip(names, part["median_days"], part["p80_days"], strict=True)
        ]
        show(
            charts.dumbbell(
                names,
                part["median_days"].tolist(),
                part["p80_days"].tolist(),
                hover,
                mode(),
                lang(),
            )
        )

    heading(t("workforce.turnover_title"), t("workforce.turnover_help"))
    turnover = dataset("turnover")
    turnover["month"] = pd.to_datetime(turnover["month"])
    turnover = turnover.sort_values("month")
    turnover["rate"] = turnover.groupby("contract_type")["rate"].transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )
    show(
        charts.small_multiples(
            turnover, "contract_type", "month", "rate", t("contract"), mode(), lang()
        )
    )


def unlocked() -> bool:
    """The assistant spends API credit, so a public deployment asks for an access code."""
    code = secret("SW_ACCESS_CODE")
    if not code or st.session_state.get("unlocked"):
        return True
    st.info(t("assistant.locked"))
    with st.form("unlock"):
        entered = st.text_input(t("assistant.code"), type="password")
        if st.form_submit_button(t("assistant.unlock")):
            if hmac.compare_digest(entered.encode(), code.encode()):
                st.session_state.unlocked = True
                st.rerun()
            st.error(t("assistant.wrong_code"))
    return False


def assistant() -> None:
    st.title(t("assistant.title"))
    st.caption(t("assistant.intro"))
    if not unlocked():
        return
    state = st.session_state
    state.setdefault("chat", [])

    if st.button(t("assistant.new"), type="tertiary"):
        state.chat, state.conversation = [], None

    for turn in state.chat:
        with st.chat_message(turn["role"], avatar=AVATAR[turn["role"]]):
            if turn["role"] == "user":
                st.markdown(turn["text"])
            else:
                render_answer(turn["answer"])

    if not state.chat and "pending" not in state:
        st.caption(t("assistant.examples"))
        for i, example in enumerate(t("assistant.ex")):
            if st.button(example, key=f"ex{i}"):
                state.pending = example
                st.rerun()

    question = st.chat_input(t("assistant.placeholder")) or state.pop("pending", None)
    if not question:
        return
    state.chat.append({"role": "user", "text": question})
    with st.chat_message("user", avatar=AVATAR["user"]):
        st.markdown(question)
    with (
        st.chat_message("assistant", avatar=AVATAR["assistant"]),
        st.spinner(t("assistant.working")),
    ):
        try:
            if not state.get("conversation"):
                state.conversation = new_conversation()
            answer = ask(state.conversation, question, lang())
        except LimitReached:
            st.warning(t("assistant.limit"))
            return
        except Exception as exc:
            st.error(t("assistant.error", error=exc))
            return
        render_answer(answer)
    state.chat.append({"role": "assistant", "answer": answer})


def render_answer(answer: dict) -> None:
    if answer.get("declined"):
        reason = t("assistant.reasons").get(answer["declined"], answer["declined"])
        st.badge(f"{t('assistant.declined')}: {reason}", color="gray")
    if not answer.get("grounded", True):
        st.warning(t("assistant.ungrounded"))
    st.markdown(answer["text"])
    for spec in answer.get("charts", []):
        st.markdown(f"**{spec['title']}**")
        fig = charts.agent_chart(spec, mode(), lang())
        if fig is None:
            st.dataframe(pd.DataFrame(spec["rows"], columns=spec["columns"]), hide_index=True)
        else:
            show(fig)
    queries = answer.get("queries", [])
    if queries:
        with st.expander(t("assistant.queries", n=len(queries))):
            for q in queries:
                st.caption(q["purpose"])
                st.code(q["sql"], language="sql")
                if q.get("error"):
                    st.caption(q["error"])
                elif q["rows"]:
                    st.dataframe(pd.DataFrame(q["rows"], columns=q["columns"]), hide_index=True)
    cost = f"${answer['cost_usd']:.3f}"
    st.caption(t("assistant.meta", q=len(queries), s=number(answer["seconds"], 1), cost=cost))
