"""The Results menu: save the current results, and open saved results without re-running (ADR 0050)."""

from datetime import datetime

import streamlit as st

from financial_simulations.retirement.saved_runs import (DEFAULT_ROOT, SavedRunError, code_changed, estimate_bytes,
                                                         list_saved_runs, load_run, save_run)
from financial_simulations.retirement.strategy_results import STRATEGY_NAMES
from financial_simulations.ui.state import calculation_cores, load_into_session, plural


def size(count):
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if count >= scale:
            return f"{count / scale:,.1f} {unit}"
    return f"{count:,} bytes"


def when(stamp):
    return f"{datetime.fromisoformat(stamp):%d %b %Y %H:%M}"


def describe(row):
    strategies = ", ".join(STRATEGY_NAMES.get(r, r) for r in row["strategies"])
    return (f"{row['name']} · {when(row['saved_at'])}" + (f" · {row['label']}" if row["label"] else "")
            + f" · {row['retirement_paths']:,} retirement paths · {strategies} · {size(row['bytes'])}"
            + (" · every path's ledger" if row["full_ledgers"] else ""))


def request_save(full, label):
    st.session_state.save_requested = {"full": full, "label": label}


def save_requested_results():
    """Save under the bar, with progress, like a run."""
    request = st.session_state.pop("save_requested", None)
    run = st.session_state.get("result")
    if request is None or run is None:
        return
    bar = st.progress(0.0, text="Saving results · 0%")

    def progress(fraction, message):
        bar.progress(min(max(fraction, 0.0), 1.0), text=f"{message} · {fraction:.0%}")

    try:
        folder = save_run(run, DEFAULT_ROOT, full_ledgers=request["full"], label=request["label"], progress=progress,
                          workers=calculation_cores())
        st.session_state.flash = f"Saved results to {folder}."
    except OSError as exc:
        st.error(f"The results could not be saved: {exc}")
        return
    finally:
        bar.empty()
    st.rerun()  # the Results menu was drawn before the save; draw it again with the new entry


def open_saved(row):
    run = load_run(row["folder"])
    load_into_session(run.plan, f"Opened saved results from {when(row['saved_at'])}.")
    st.session_state.plan_file = None
    st.session_state.result = run
    st.session_state.ledger_cache, st.session_state.derived = {}, {}
    st.session_state.pop("paths_image_cache", None)
    st.session_state.saved_code_changed = code_changed(row["code"])
    st.session_state.page = "Outcomes"


def results_menu(run):
    """Save the results on screen, or open saved ones."""
    if run is not None and run.saved_from is not None:
        st.markdown(f"**These results were opened from** `{run.saved_from.as_posix()}`.")
        if run.saved_ledgers is not None:
            st.caption("Every path's full daily ledger was saved, so opening a path reads it instead of re-running it.")
        else:
            st.caption("Opening a path other than the median one re-runs its daily ledger from the saved draws "
                       "(about a second).")
        if st.session_state.get("saved_code_changed"):
            st.warning("The model's code has changed since these results were saved. They are the results of the "
                       "code that saved them (recorded in run.json); run the plan again for current results.")
    elif run is not None:
        base, ledgers = estimate_bytes(run.plan)
        st.markdown("**Save these results**")
        label = st.text_input("Note (optional)", key="save_label", max_chars=80,
                              help="Shown in the list of saved results, for example what this run tests.")
        full = st.checkbox("Also save every path's full daily ledger", value=False, key="save_full_ledgers",
                           help="Every calculated path's day-by-day balances, flows and event log, for each strategy. "
                                f"It re-runs every path's ledger on the same draws and writes them, which can take "
                                f"longer than the run itself, and adds about {size(ledgers)}. Without it, opening a path re-runs "
                                "its ledger in about a second.")
        st.caption(f"About {size(base + (ledgers if full else 0))}, saved to `{DEFAULT_ROOT.as_posix()}/` (git-ignored).")
        st.button("Save results", width="stretch", key="save_results", icon=":material/save:", on_click=request_save,
                  args=(full, label))
    else:
        st.caption("Run the plan to save its results.")
    saved = list_saved_runs(DEFAULT_ROOT)
    st.divider()
    if not saved:
        st.caption(f"No saved results yet in `{DEFAULT_ROOT.as_posix()}/`.")
        return
    rows = {describe(row): row for row in saved}
    choice = st.selectbox(f"Open saved results ({plural(len(saved), 'run')})", list(rows), key="saved_pick")
    row = rows[choice]
    st.caption(f"{plural(row['files'], 'file')} in `{row['folder'].as_posix()}`.")
    if st.button("Open", width="stretch", key="open_saved", icon=":material/folder_open:",
                 help="Replaces the plan and results on screen with the saved ones."):
        try:
            open_saved(row)
            st.rerun()
        except (SavedRunError, OSError, KeyError, ValueError) as exc:
            st.error(f"Could not open {row['folder']}: {exc}")
