"""Saving results with a plan, and opening saved results, from the Plan menu (ADRs 0050 and 0051)."""

import copy
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


def request_save(full, label="", plan_file=None):
    st.session_state.save_requested = {"full": full, "label": label, "plan_file": plan_file}


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
        plan_file = request.get("plan_file")
        st.session_state.flash = (f"Saved {plan_file} and its results to {folder}." if plan_file
                                  else f"Saved results to {folder}.")
    except OSError as exc:
        st.error(f"The results could not be saved: {exc}")
        return
    finally:
        bar.empty()
    st.rerun()  # the Plan menu was drawn before the save; draw it again with the new entry


def open_saved(row):
    run = load_run(row["folder"])
    # The editor gets its own copy: edits must not change the plan the opened results belong to.
    load_into_session(copy.deepcopy(run.plan), f"Opened saved results from {when(row['saved_at'])}.")
    st.session_state.plan_file = None
    st.session_state.result = run
    st.session_state.ledger_cache, st.session_state.derived = {}, {}
    st.session_state.pop("paths_image_cache", None)
    st.session_state.saved_code_changed = code_changed(row["code"])
    st.session_state.page = "Outcomes"


RESULTS_BOX, LEDGERS_BOX = "save_results_too", "save_full_ledgers"


def save_options(run, current):
    """The Plan menu's tick boxes for saving the results with the plan. Returns (save results, every ledger).

    ``current`` says the results on screen are those of the plan being saved. Otherwise both boxes are greyed out
    and cleared, so a plan file is never saved beside results of different inputs.
    """
    possible = run is not None and current
    if not possible:
        st.session_state[RESULTS_BOX] = st.session_state[LEDGERS_BOX] = False
    why = ("Run the plan first: there are no results to save." if run is None else
           "The inputs have changed since the last run: run the plan again to save results that match it."
           if not current else None)
    base, ledgers = estimate_bytes(run.plan) if run is not None else (0, 0)
    results = st.checkbox("Also save results", key=RESULTS_BOX, disabled=not possible,
                          help=why or f"Saves the results on screen to `{DEFAULT_ROOT.as_posix()}/` (git-ignored), so they "
                                      "open again without re-running.")
    if not results:
        st.session_state[LEDGERS_BOX] = False
    full = st.checkbox("Also save every path's full daily ledger", key=LEDGERS_BOX, disabled=not results,
                       help="Every calculated path's day-by-day balances, flows and event log, for each strategy. It "
                            "re-runs every path's ledger on the same draws and writes them, which can take longer than "
                            f"the run itself, and adds about {size(ledgers)}. Without it, opening a path re-runs its "
                            "ledger in about a second.")
    if results:
        st.caption(f"Results: about {size(base + (ledgers if full else 0))}.")
    return results, full


def opened_note(run):
    """Where results opened from a save came from, and whether the code has changed since."""
    if run is None or run.saved_from is None:
        return
    st.caption(f"Results opened from `{run.saved_from.as_posix()}`" +
               (", with every path's ledger." if run.saved_ledgers is not None else "."))
    if st.session_state.get("saved_code_changed"):
        st.warning("The model's code has changed since these results were saved. They are the results of the code "
                   "that saved them (recorded in run.json); run the plan again for current results.")


def open_saved_results():
    """Pick a saved run and open its plan and results."""
    saved = list_saved_runs(DEFAULT_ROOT)
    if not saved:
        return
    rows = {describe(row): row for row in saved}
    a, b = st.columns([2.2, 1], vertical_alignment="bottom")
    choice = a.selectbox(f"Open saved results ({plural(len(saved), 'run')})", list(rows), key="saved_pick",
                         help="Saved with **Also save results**. Opening one replaces the plan and results on screen.")
    row = rows[choice]
    if b.button("Open", width="stretch", key="open_saved"):
        try:
            open_saved(row)
            st.rerun()
        except (SavedRunError, OSError, KeyError, ValueError) as exc:
            st.error(f"Could not open {row['folder']}: {exc}")
    st.caption(f"{plural(row['files'], 'file')} in `{row['folder'].as_posix()}`.")
