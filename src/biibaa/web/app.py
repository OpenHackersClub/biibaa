"""NiceGUI triage UI for biibaa briefs.

Sortable + filterable table of all briefs in `data/briefs/`. Click a row to
preview the brief markdown in a side pane.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nicegui import ui

from biibaa.web.loader import BriefRow, latest_per_slug, load_briefs

_HEAD_CSS = """\

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --triage-bg: #0b1020;
    --triage-surface: #11172a;
    --triage-surface-2: #19223d;
    --triage-border: rgba(148, 163, 184, 0.12);
    --triage-text: #e2e8f0;
    --triage-muted: #94a3b8;
    --triage-accent: #818cf8;
  }
  body {
    font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
    background: radial-gradient(1200px 600px at 80% -10%, rgba(129,140,248,0.12), transparent 60%),
                radial-gradient(900px 500px at -10% 110%, rgba(56,189,248,0.10), transparent 55%),
                var(--triage-bg) !important;
    color: var(--triage-text);
    letter-spacing: -0.005em;
  }
  .triage-shell { padding: 16px 20px; }
  .triage-title { font-weight: 700; letter-spacing: -0.025em; }
  .triage-subtle { color: var(--triage-muted); }
  .triage-card {
    background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
    border: 1px solid var(--triage-border);
    border-radius: 14px;
    padding: 14px 16px;
    backdrop-filter: blur(8px);
  }
  /* Quasar table polish */
  .q-table__container { border-radius: 14px; border: 1px solid var(--triage-border); background: var(--triage-surface); }
  .q-table thead tr th {
    position: sticky; top: 0; z-index: 2;
    background: var(--triage-surface-2) !important;
    color: var(--triage-text) !important;
    font-weight: 600; font-size: 12.5px; letter-spacing: 0.02em; text-transform: uppercase;
    border-bottom: 1px solid var(--triage-border) !important;
  }
  .q-table tbody tr { transition: background 120ms ease; }
  .q-table tbody tr:hover { background: rgba(129,140,248,0.07) !important; cursor: pointer; }
  .q-table tbody td { border-bottom: 1px solid var(--triage-border) !important; font-size: 13.5px; }
  .q-table .mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, monospace; font-size: 12.5px; }
  .q-table__bottom { border-top: 1px solid var(--triage-border); }
  /* Sort chips */
  .sort-bar { gap: 8px; flex-wrap: wrap; align-items: center; }
  .sort-chip { cursor: pointer; user-select: none; }
  /* Markdown preview tweaks */
  .triage-preview { background: var(--triage-surface); border: 1px solid var(--triage-border); border-radius: 14px; padding: 18px 22px; }
  .triage-preview h1 { font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem; }
  .triage-preview h2 { font-size: 1.05rem; font-weight: 600; margin-top: 1rem; color: var(--triage-accent); }
  .triage-preview h3 { font-size: 0.95rem; font-weight: 600; margin-top: 0.75rem; }
  .triage-preview a { color: var(--triage-accent); text-decoration: none; }
  .triage-preview a:hover { text-decoration: underline; }
  .triage-preview code { background: rgba(148,163,184,0.12); padding: 1px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 0.85em; }
  .triage-preview ul { margin-left: 1.2rem; }
  .triage-preview li { margin: 0.15rem 0; }
</style>
"""

# Each column declares only what we render — the multi-sort picker drives sort
# entirely server-side, so no `sortable` flag here (the chip bar is the source
# of truth and Quasar's column-header sort is intentionally disabled).
_COLUMNS: list[dict[str, Any]] = [
    {"name": "slug", "label": "Project", "field": "slug", "align": "left", "classes": "mono"},
    {"name": "ecosystem", "label": "Eco", "field": "ecosystem", "align": "center"},
    {"name": "score", "label": "Score", "field": "score", "align": "right"},
    {"name": "impact", "label": "Impact", "field": "impact", "align": "right"},
    {"name": "effort", "label": "Effort", "field": "effort", "align": "right"},
    {"name": "confidence", "label": "Conf", "field": "confidence", "align": "right"},
    {"name": "opps", "label": "Opps", "field": "opps", "align": "right"},
    {"name": "top_kind", "label": "Top kind", "field": "top_kind", "align": "left"},
    {
        "name": "last_pr_merged",
        "label": "LastPRMerged",
        "field": "last_pr_merged",
        "align": "left",
        "classes": "mono",
    },
    {"name": "bench", "label": "Bench", "field": "bench", "align": "center"},
    {"name": "archived", "label": "Arch", "field": "archived", "align": "center"},
    {"name": "tags", "label": "Tags", "field": "tags", "align": "left"},
    {"name": "date", "label": "Date", "field": "date", "align": "center", "classes": "mono"},
]

_LABELS: dict[str, str] = {c["name"]: c["label"] for c in _COLUMNS}

# Sortable columns (excludes "tags" — list value, no sensible total order).
_SORT_COLUMNS: tuple[str, ...] = (
    "slug",
    "ecosystem",
    "score",
    "impact",
    "effort",
    "confidence",
    "opps",
    "top_kind",
    "last_pr_merged",
    "bench",
    "archived",
    "date",
)


def _row_dict(b: BriefRow) -> dict[str, Any]:
    fm = b.frontmatter
    score = fm.get("score") or {}
    project = fm.get("project") or {}
    activity = fm.get("maintainer_activity") or {}
    bench = fm.get("benchmarks") or {}
    opps = fm.get("opportunities") or {}
    last_pr = activity.get("last_pr_merged_at") or ""
    last_pr_date = last_pr.split("T", 1)[0] if last_pr else ""
    return {
        "slug": b.slug,
        "ecosystem": project.get("ecosystem", ""),
        "score": round(float(score.get("total") or 0), 1),
        "impact": round(float(score.get("impact") or 0), 1),
        "effort": round(float(score.get("effort") or 0), 1),
        "confidence": int(score.get("confidence") or 0),
        "opps": int(opps.get("count") or 0),
        "top_kind": opps.get("top_kind") or "",
        "last_pr_merged": last_pr_date,
        "bench": "yes" if bench.get("has") else ("no" if "has" in bench else "?"),
        "archived": "yes" if project.get("archived") else "no",
        "tags": fm.get("tags") or [],
        "date": b.date,
    }


def build_app(briefs_dir: Path) -> None:
    ui.add_head_html(_HEAD_CSS)

    all_briefs = load_briefs(briefs_dir)

    state: dict[str, Any] = {
        "show_all_dates": False,
        "ecosystem": None,
        "top_kind": None,
        "tag": None,
        "min_score": 0,
        "hide_archived": True,
        "bench_filter": "any",
        "search": "",
        # Multi-column sort: list of (column_name, descending). Highest priority first.
        "sort_keys": [("score", True)],
    }

    by_key: dict[tuple[str, str], BriefRow] = {(b.slug, b.date): b for b in all_briefs}

    ecosystems = sorted(
        {(b.frontmatter.get("project") or {}).get("ecosystem") or "" for b in all_briefs}
        - {""}
    )
    top_kinds = sorted(
        {(b.frontmatter.get("opportunities") or {}).get("top_kind") or "" for b in all_briefs}
        - {""}
    )
    all_tags = sorted({t for b in all_briefs for t in (b.frontmatter.get("tags") or [])})

    def _passes_filters(b: BriefRow) -> bool:
        fm = b.frontmatter
        project = fm.get("project") or {}
        score_total = (fm.get("score") or {}).get("total") or 0
        tags = set(fm.get("tags") or [])
        if state["ecosystem"] and project.get("ecosystem") != state["ecosystem"]:
            return False
        if (
            state["top_kind"]
            and (fm.get("opportunities") or {}).get("top_kind") != state["top_kind"]
        ):
            return False
        if state["tag"] and state["tag"] not in tags:
            return False
        if score_total < state["min_score"]:
            return False
        if state["hide_archived"] and project.get("archived"):
            return False
        bench_has = (fm.get("benchmarks") or {}).get("has")
        if state["bench_filter"] == "yes" and not bench_has:
            return False
        if state["bench_filter"] == "no" and bench_has:
            return False
        return not (
            state["search"] and state["search"].lower() not in b.slug.lower()
        )

    def _sort_key(row: dict[str, Any], col: str) -> Any:
        v = row.get(col)
        # Lists (tags column shouldn't reach here, but be defensive).
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return v if v is not None else ""

    def visible_rows() -> list[dict[str, Any]]:
        base = all_briefs if state["show_all_dates"] else latest_per_slug(all_briefs)
        rows = [_row_dict(b) for b in base if _passes_filters(b)]
        # Stable iterative sort from lowest priority to highest.
        for col, desc in reversed(state["sort_keys"]):
            rows.sort(key=lambda r, col=col: _sort_key(r, col), reverse=desc)
        return rows

    # ---------- Sort + filter mutators (declared before UI so render_* can capture them) ----------

    refreshables: dict[str, Any] = {}

    def _refresh_all() -> None:
        if "sort_bar" in refreshables:
            refreshables["sort_bar"].refresh()
        if "table" in refreshables:
            refreshables["table"].refresh()

    def _flip_sort(idx: int) -> None:
        if 0 <= idx < len(state["sort_keys"]):
            col, desc = state["sort_keys"][idx]
            state["sort_keys"][idx] = (col, not desc)
            _refresh_all()

    def _remove_sort(idx: int) -> None:
        if 0 <= idx < len(state["sort_keys"]):
            state["sort_keys"].pop(idx)
            _refresh_all()

    def _add_sort(col: str) -> None:
        state["sort_keys"].append((col, True))
        _refresh_all()

    def _reset_sort() -> None:
        state["sort_keys"] = [("score", True)]
        _refresh_all()

    # ---------- Header ----------

    with ui.column().classes("triage-shell w-full gap-3"):
        with ui.row().classes("items-baseline gap-3 w-full"):
            ui.label("biibaa briefs").classes("triage-title text-3xl")
            ui.label("· triage").classes("text-2xl triage-subtle")
            ui.space()
            ui.label(f"{len(all_briefs)} briefs · {len(by_key)} unique dates").classes(
                "triage-subtle text-sm"
            )

        # ---------- Filters card ----------
        with ui.element("div").classes("triage-card w-full"):
            with ui.row().classes("gap-3 items-end flex-wrap"):
                eco_select = ui.select(
                    [None, *ecosystems], label="Ecosystem", value=None, clearable=True
                ).classes("w-40").props("dense outlined")
                kind_select = ui.select(
                    [None, *top_kinds], label="Top kind", value=None, clearable=True
                ).classes("w-44").props("dense outlined")
                tag_select = ui.select(
                    [None, *all_tags], label="Tag", value=None, clearable=True
                ).classes("w-36").props("dense outlined")
                bench_select = (
                    ui.select(["any", "yes", "no"], label="Bench", value="any")
                    .classes("w-24")
                    .props("dense outlined")
                )
                score_input = (
                    ui.number(label="Min score", value=0, min=0, max=100, step=5)
                    .classes("w-28")
                    .props("dense outlined")
                )
                archived_toggle = ui.switch("Hide archived", value=True)
                all_dates_toggle = ui.switch("All dates", value=False)
                search_input = (
                    ui.input(label="Search slug")
                    .classes("w-48")
                    .props("dense outlined clearable")
                )

        # ---------- Sort bar ----------
        @ui.refreshable
        def _render_sort_bar() -> None:
            with ui.row().classes("sort-bar"):
                ui.label("Sort by").classes("text-sm triage-subtle")
                if not state["sort_keys"]:
                    ui.label("(none)").classes("text-sm italic triage-subtle")
                for i, (col, desc) in enumerate(state["sort_keys"]):
                    label = _LABELS.get(col, col)
                    arrow = "↓" if desc else "↑"
                    chip = ui.chip(
                        f"{label} {arrow}",
                        removable=True,
                        color="indigo-7",
                        text_color="white",
                    ).classes("sort-chip").props("dense")
                    chip.on("click", lambda _e, idx=i: _flip_sort(idx))
                    chip.on(
                        "update:model-value",
                        lambda e, idx=i: _remove_sort(idx) if e.args is False else None,
                    )
                # "+ add sort" menu over remaining columns.
                used = {k[0] for k in state["sort_keys"]}
                remaining = [c for c in _SORT_COLUMNS if c not in used]
                if remaining:
                    with ui.button(icon="add").props("flat dense round size=sm color=indigo-3"):
                        with ui.menu():
                            for col in remaining:
                                ui.menu_item(
                                    _LABELS.get(col, col),
                                    on_click=lambda _e, col=col: _add_sort(col),
                                )
                if state["sort_keys"]:
                    ui.button(
                        "Reset",
                        on_click=_reset_sort,
                    ).props("flat dense size=sm color=grey-5")

        refreshables["sort_bar"] = _render_sort_bar
        _render_sort_bar()

        # ---------- Table + preview ----------

        detail_holder: dict[str, Any] = {}

        def _on_row_click(e: Any) -> None:
            args = e.args
            row = args[1] if isinstance(args, list) and len(args) > 1 else args
            if not isinstance(row, dict):
                return
            b = by_key.get((row.get("slug", ""), row.get("date", "")))
            if b is None:
                for k, v in by_key.items():
                    if k[0] == row.get("slug"):
                        b = v
                        break
            md = detail_holder.get("md")
            if b is not None and md is not None:
                md.set_content(b.body)

        @ui.refreshable
        def _render_table() -> None:
            rows = visible_rows()
            t = ui.table(
                columns=_COLUMNS,
                rows=rows,
                row_key="slug",
                pagination=25,
            ).classes("w-full").props("flat dense")
            t.add_slot(
                "top-right",
                """
                <q-input v-model="props.filter" placeholder="quick filter" dense outlined>
                  <template v-slot:append><q-icon name="search"/></template>
                </q-input>
                """,
            )
            # Color-coded score chip.
            t.add_slot(
                "body-cell-score",
                """
                <q-td :props="props" class="text-right">
                  <q-chip dense
                    :color="props.value >= 70 ? 'positive' : props.value >= 50 ? 'amber-7' : 'grey-7'"
                    text-color="white"
                    :label="props.value"/>
                </q-td>
                """,
            )
            # Render tags as small chips.
            t.add_slot(
                "body-cell-tags",
                """
                <q-td :props="props">
                  <q-chip v-for="tag in props.value" :key="tag"
                          size="sm" outline color="indigo-3" text-color="indigo-2"
                          :label="tag" dense class="q-mr-xs"/>
                </q-td>
                """,
            )
            t.on("rowClick", _on_row_click)

        refreshables["table"] = _render_table

        with ui.splitter(value=58).classes("w-full h-[80vh]") as splitter:
            with splitter.before:
                with ui.element("div").classes("w-full pr-3"):
                    _render_table()

            with splitter.after:
                with ui.element("div").classes("triage-preview ml-3 mt-1 overflow-auto h-[78vh]"):
                    detail_holder["md"] = ui.markdown(
                        "Click a row to preview the brief here."
                    )

    def _bind(key: str, transform: Any = lambda v: v) -> Any:
        def handler(e: Any) -> None:
            state[key] = transform(e.value)
            _render_table.refresh()

        return handler

    eco_select.on_value_change(_bind("ecosystem"))
    kind_select.on_value_change(_bind("top_kind"))
    tag_select.on_value_change(_bind("tag"))
    bench_select.on_value_change(_bind("bench_filter", lambda v: v or "any"))
    score_input.on_value_change(_bind("min_score", lambda v: v or 0))
    archived_toggle.on_value_change(_bind("hide_archived"))
    all_dates_toggle.on_value_change(_bind("show_all_dates"))
    search_input.on_value_change(_bind("search", lambda v: v or ""))


def serve(
    briefs_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    show: bool = False,
) -> None:
    @ui.page("/")
    def index() -> None:
        build_app(briefs_dir)

    ui.run(host=host, port=port, title="biibaa triage", reload=False, show=show)
