"""Browser app for editing, importing, exporting and running a retirement plan.

Launch with ``financial-simulations ui`` (or ``streamlit run`` on this file).
The plan dictionary in session state is the single source of truth: the Plan
page edits it, the plan menu imports and exports it, and Run writes one folder,
output/plans/<plan-name>/. A bar that stays on screen holds the pages, the plan
menu (which also saves and opens results: ADRs 0050 and 0051) and Run; only the
open page is drawn (ADR 0047).
"""

from datetime import date
from html import escape

import streamlit as st

from financial_simulations.retirement.outcomes import PATH_GROUPS, ending_percentiles, group_members  # noqa: F401
from financial_simulations.retirement.paths import warm_pool
from financial_simulations.retirement.plan import (PlanError, default_plan, load_plan_text, normalize_plan, plan_to_json,
                                                   plan_to_toml, slug)
from financial_simulations.retirement.run_plan import run_plan
from financial_simulations.rules.au.parameters import UnsupportedRule
from financial_simulations.ui import charts, inputs, more_pages, outcomes_page, paths_page
from financial_simulations.ui import saved as saved_results
from financial_simulations.ui.charts import SHOWN_PATHS, shown_paths  # noqa: F401
from financial_simulations.ui.results import no_results
from financial_simulations.ui.state import (PLANS_DIR, affected, cached_market, calculation_cores, keep_sticky, key,  # noqa: F401
                                            load_into_session, ordinal)
from financial_simulations.ui.theme import apply_styles


PAGES = {"Plan": ":material/edit_note: Plan", "Outcomes": ":material/insights: Outcomes",
         "Paths": ":material/timeline: Paths", "Compare": ":material/compare_arrows: Compare",
         "Markets": ":material/show_chart: Markets", "Method": ":material/menu_book: Method"}


@st.cache_resource(show_spinner=False)
def start_ledger_workers(count, cores=None):
    """Start the tax-ledger worker processes once per app server, so the first run does not wait for them."""
    warm_pool(count, cores)
    return True


def request_run():
    st.session_state.run_requested = True


def run_with_progress(valid):
    bar = st.progress(0.0, text="Loading ticker histories · 0%")

    def progress(fraction, message):
        bar.progress(min(max(fraction, 0.0), 1.0), text=f"{message} · {fraction:.0%}")

    try:
        market = cached_market(tuple(valid["assets"]))
        return run_plan(valid, market=market, progress=progress, workers=calculation_cores())
    finally:
        bar.empty()


def run_requested_plan():
    """Run under the bar, so the progress shows at once whichever page is open, then open the outcomes."""
    if not st.session_state.pop("run_requested", False):
        return
    try:
        valid = normalize_plan(st.session_state.plan)
    except PlanError:
        st.session_state.page = "Plan"
        return
    try:
        st.session_state.result = run_with_progress(valid)
        st.session_state.ledger_cache, st.session_state.derived = {}, {}
        st.session_state.pop("paths_image_cache", None)
        st.session_state.page = "Outcomes"
        st.session_state.flash = "Run complete."
    except (UnsupportedRule, PlanError, ValueError, ArithmeticError) as exc:
        st.session_state.result = None
        st.error(f"The plan cannot run as specified: {exc}")


def save_plan(valid, path):
    PLANS_DIR.mkdir(exist_ok=True)
    path.write_text(plan_to_toml(valid), encoding="utf-8", newline="\n")
    st.session_state.plan_file = path.name
    st.session_state.flash = f"Saved {path}."


def plan_menu(plan, valid, run):
    """The plan's name and file: save (with its results if ticked), rename, open plans or saved results, import,
    download and reset."""
    saved_results.opened_note(run)
    plan["plan"]["name"] = st.text_input("Plan name", plan["plan"]["name"], key=key("name"),
                                         help="Also the file name: saving writes plans/<plan-name>.toml.")
    current = st.session_state.get("plan_file")
    if valid is None:
        st.info("Fix the plan's problems before saving.")
    else:
        target = PLANS_DIR / f"{slug(valid['plan']['name'])}.toml"
        renaming = current is not None and current != target.name and (PLANS_DIR / current).exists()
        up_to_date = run is not None and plan_to_json(valid) == plan_to_json(run.plan)
        results, full = saved_results.save_options(run, up_to_date)
        a, b = st.columns(2)
        if a.button("Save", width="stretch", key="save_plan", icon=":material/save:",
                    help=f"Write {target}" + (", replacing it" if target.exists() else "")
                         + (", and save the results" if results else "")):
            save_plan(valid, target)
            if results:
                saved_results.request_save(full, plan_file=target)
            st.rerun()
        if renaming and b.button("Rename", width="stretch", key="rename_plan",
                                 help=f"Save as {target.name} and remove {current}, so only the new name remains."):
            save_plan(valid, target)
            (PLANS_DIR / current).unlink()
            st.session_state.flash = f"Renamed {current} to {target.name}."
            st.rerun()
        if renaming:
            st.caption(f"**Save** keeps `{current}` and writes `{target.name}` as a copy; **Rename** replaces it.")
        elif target.exists() and current != target.name:
            st.warning(f"`{target.name}` already exists; Save will overwrite it.")
    saved = sorted(PLANS_DIR.glob("*.toml")) + sorted(PLANS_DIR.glob("*.json")) if PLANS_DIR.exists() else []
    if saved:
        names = [f.name for f in saved]
        a, b = st.columns([2.2, 1], vertical_alignment="bottom")
        choice = a.selectbox("Open a saved plan", names, key=key(f"saved_{current}"),
                             index=names.index(current) if current in names else 0)
        if b.button("Open", width="stretch", key="open_plan"):
            chosen = PLANS_DIR / choice
            try:
                load_into_session(load_plan_text(chosen.read_text(encoding="utf-8"), chosen.name), f"Opened {chosen}.")
                st.session_state.plan_file = chosen.name
                st.rerun()
            except PlanError as exc:
                st.error(str(exc))
    saved_results.open_saved_results()
    with st.expander("Import or download a plan file"):
        upload = st.file_uploader("Import a plan (.toml or .json)", type=["toml", "json"], key=key("upload"))
        if upload is not None:
            try:
                load_into_session(load_plan_text(upload.getvalue().decode("utf-8"), upload.name), f"Imported {upload.name}.")
                st.session_state.plan_file = None
                st.rerun()
            except (PlanError, UnicodeDecodeError) as exc:
                st.error(f"Could not import {upload.name}: {exc}")
        if valid is not None:
            name = slug(valid["plan"]["name"])
            st.download_button("Download as TOML", plan_to_toml(valid), f"{name}.toml", "application/toml", width="stretch")
            st.download_button("Download as JSON", plan_to_json(valid), f"{name}.json", "application/json", width="stretch")
    if st.button("Start again from the example plan", width="stretch", key="reset_plan"):
        load_into_session(default_plan(), "Loaded the example plan.")
        st.session_state.plan_file = None
        st.rerun()
    st.caption(f"Saved plans live in `{PLANS_DIR}/` and saved results in `output/saved_runs/` (both git-ignored). "
               "Runs write `output/plans/<plan-name>/`.")


def top_bar(plan, valid, pages):
    """Brand and plan name, the pages, the run's status, the plan menu and Run. Returns the open page."""
    run = st.session_state.result
    current = st.session_state.get("page", "Plan")
    current = current if current in pages else pages[0]
    if st.session_state.get("nav") not in pages:  # first run, a page that went away, or a click on the open page
        st.session_state["nav"] = current
    elif st.session_state.get("_nav_sync") != current:  # the app changed page itself (after a run)
        st.session_state["nav"] = current
    with st.container(key="topbar"):
        brand, nav, status, menu, go = st.columns([1.5, 4.6, 1.5, 0.9, 1.1], vertical_alignment="center")
        saved = st.session_state.get("plan_file")
        brand.html(f"<div class='brand'>Retirement planner<small>{escape(plan['plan']['name'])}"
                   f"{'' if saved else ' · not saved'}</small></div>")
        with nav:
            choice = st.segmented_control("Page", pages, format_func=PAGES.get, key="nav", label_visibility="collapsed")
        if valid is None:
            text, colour = "Plan has problems to fix", "#9b1c3c"
        elif run is None:
            text, colour = "Not run yet", "#a8a69d"
        elif plan_to_json(valid) != plan_to_json(run.plan):
            text, colour = "Inputs changed since the last run", "#eda100"
        elif run.saved_from is not None:
            text, colour = "Saved results opened", "#1baf7a"
        else:
            text, colour = "Results are up to date", "#1baf7a"
        status.html(f"<div class='status'><span class='dot' style='background:{colour}'></span>{text}</div>")
        with menu.popover("Plan", icon=":material/folder_open:", width="stretch"):
            plan_menu(plan, valid, run)
        go.button("Run plan", type="primary", width="stretch", key="run_sidebar", on_click=request_run,
                  icon=":material/play_arrow:", disabled=valid is None)
    st.session_state.page = st.session_state["_nav_sync"] = choice or current
    return st.session_state.page


def main():
    st.set_page_config(page_title="Retirement planner", page_icon=":material/savings:", layout="wide",
                       initial_sidebar_state="collapsed")
    if "plan" not in st.session_state:
        st.session_state.plan, st.session_state.version, st.session_state.result = default_plan(), 0, None
    apply_styles()
    keep_sticky()
    message = st.session_state.pop("flash", None)
    if message:
        st.toast(message)
    plan = st.session_state.plan
    start_ledger_workers(plan["market"]["retirement_paths"], calculation_cores())
    try:
        valid, problems = normalize_plan(plan), []
    except PlanError as exc:
        valid, problems = None, exc.problems
    run = st.session_state.result
    if run is not None and not hasattr(run, "saved_from"):  # the newest PlanRun field; an old server's modules lack it
        st.session_state.result = run = None
    compared = run is not None and len(run.strategies or {}) > 1
    pages = [name for name in PAGES if name != "Compare" or compared]
    page = top_bar(plan, valid, pages)
    run_requested_plan()
    saved_results.save_requested_results()
    if st.session_state.get("page") != page:  # a run finished and opened the outcomes
        st.rerun()
    run = st.session_state.result
    if page == "Plan":
        if problems:
            st.error("The plan has problems to fix before it can run:\n" + "\n".join(f"- `{p}`" for p in problems))
        inputs.page(plan)
        return
    if run is None:
        no_results(page)
        return
    charts.BORN["date"] = date.fromisoformat(run.plan["person"]["date_of_birth"])
    if page == "Outcomes":
        outcomes_page.page(run)
    elif page == "Paths":
        paths_page.page(run)
    elif page == "Compare":
        more_pages.compare_page(run)
    elif page == "Markets":
        more_pages.markets_page(run)
    else:
        more_pages.method_page(run)


main()
