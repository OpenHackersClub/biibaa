"""NiceGUI triage UI for biibaa briefs.

Sortable + filterable table of all briefs in `data/briefs/`. Click a row to
preview the brief markdown in a side pane.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nicegui import ui

from biibaa.web.loader import BriefRow, latest_per_slug, load_briefs

_COLUMNS: list[dict[str, Any]] = [
    {"name": "slug", "label": "Project", "field": "slug", "sortable": True, "align": "left"},
    {"name": "ecosystem", "label": "Eco", "field": "ecosystem", "sortable": True},
    {"name": "score", "label": "Score", "field": "score", "sortable": True},
    {"name": "impact", "label": "Impact", "field": "impact", "sortable": True},
    {"name": "effort", "label": "Effort", "field": "effort", "sortable": True},
    {"name": "confidence", "label": "Conf", "field": "confidence", "sortable": True},
    {"name": "opps", "label": "Opps", "field": "opps", "sortable": True},
    {"name": "top_kind", "label": "Top kind", "field": "top_kind", "sortable": True, "align": "left"},
    {"name": "activity", "label": "Activity", "field": "activity", "sortable": True, "align": "left"},
    {"name": "bench", "label": "Bench", "field": "bench", "sortable": True},
    {"name": "archived", "label": "Arch", "field": "archived", "sortable": True},
    {"name": "tags", "label": "Tags", "field": "tags", "sortable": False, "align": "left"},
    {"name": "date", "label": "Date", "field": "date", "sortable": True},
]


def _row_dict(b: BriefRow) -> dict[str, Any]:
    fm = b.frontmatter
    score = fm.get("score") or {}
    project = fm.get("project") or {}
    activity = fm.get("maintainer_activity") or {}
    bench = fm.get("benchmarks") or {}
    opps = fm.get("opportunities") or {}
    return {
        "slug": b.slug,
        "ecosystem": project.get("ecosystem", ""),
        "score": score.get("total", 0),
        "impact": score.get("impact", 0),
        "effort": score.get("effort", 0),
        "confidence": score.get("confidence", 0),
        "opps": opps.get("count", 0),
        "top_kind": opps.get("top_kind") or "",
        "activity": activity.get("label", ""),
        "bench": "yes" if bench.get("has") else ("no" if "has" in bench else "?"),
        "archived": "yes" if project.get("archived") else "no",
        "tags": ", ".join(fm.get("tags") or []),
        "date": b.date,
    }


def build_app(briefs_dir: Path) -> None:
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
    }

    by_key: dict[tuple[str, str], BriefRow] = {(b.slug, b.date): b for b in all_briefs}

    ecosystems = sorted(
        {(b.frontmatter.get("project") or {}).get("ecosystem") or "" for b in all_briefs} - {""}
    )
    top_kinds = sorted(
        {(b.frontmatter.get("opportunities") or {}).get("top_kind") or "" for b in all_briefs}
        - {""}
    )
    all_tags = sorted({t for b in all_briefs for t in (b.frontmatter.get("tags") or [])})

    def visible() -> list[BriefRow]:
        base = all_briefs if state["show_all_dates"] else latest_per_slug(all_briefs)
        out: list[BriefRow] = []
        for b in base:
            fm = b.frontmatter
            project = fm.get("project") or {}
            score_total = (fm.get("score") or {}).get("total") or 0
            tags = set(fm.get("tags") or [])
            if state["ecosystem"] and project.get("ecosystem") != state["ecosystem"]:
                continue
            if (
                state["top_kind"]
                and (fm.get("opportunities") or {}).get("top_kind") != state["top_kind"]
            ):
                continue
            if state["tag"] and state["tag"] not in tags:
                continue
            if score_total < state["min_score"]:
                continue
            if state["hide_archived"] and project.get("archived"):
                continue
            bench_has = (fm.get("benchmarks") or {}).get("has")
            if state["bench_filter"] == "yes" and not bench_has:
                continue
            if state["bench_filter"] == "no" and bench_has:
                continue
            if state["search"] and state["search"].lower() not in b.slug.lower():
                continue
            out.append(b)
        return out

    ui.dark_mode().enable()
    with ui.row().classes("items-center gap-3 w-full"):
        ui.label("biibaa briefs — triage").classes("text-2xl font-bold")
        ui.label(f"{len(all_briefs)} briefs total").classes("text-gray-500")

    with ui.row().classes("gap-3 items-end flex-wrap"):
        eco_select = ui.select(
            [None, *ecosystems], label="Ecosystem", value=None, clearable=True
        ).classes("w-40")
        kind_select = ui.select(
            [None, *top_kinds], label="Top kind", value=None, clearable=True
        ).classes("w-44")
        tag_select = ui.select(
            [None, *all_tags], label="Tag", value=None, clearable=True
        ).classes("w-36")
        bench_select = ui.select(["any", "yes", "no"], label="Bench", value="any").classes("w-24")
        score_input = ui.number(label="Min score", value=0, min=0, max=100, step=5).classes("w-28")
        archived_toggle = ui.switch("Hide archived", value=True)
        all_dates_toggle = ui.switch("Show all dates", value=False)
        search_input = ui.input(label="Search slug").classes("w-44")

    detail_holder: dict[str, Any] = {}

    def _on_row_click(e: Any) -> None:
        # Quasar rowClick payload: [event, row, index]
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
        detail = detail_holder.get("md")
        if b is not None and detail is not None:
            detail.set_content(b.body)

    @ui.refreshable
    def render_table() -> None:
        rows = [_row_dict(b) for b in visible()]
        t = ui.table(
            columns=_COLUMNS,
            rows=rows,
            row_key="slug",
            pagination=25,
        ).classes("w-full")
        t.add_slot(
            "top-right",
            """
            <q-input v-model="props.filter" placeholder="quick filter" dense outlined>
              <template v-slot:append><q-icon name="search"/></template>
            </q-input>
            """,
        )
        t.on("rowClick", _on_row_click)

    with ui.splitter(value=60).classes("w-full h-[80vh]") as splitter:
        with splitter.before:
            render_table()

        with splitter.after:
            ui.label("Brief preview").classes("text-lg font-semibold ml-3 mt-3")
            detail_holder["md"] = ui.markdown("Click a row to preview the brief.").classes(
                "border rounded p-3 m-3 overflow-auto h-[72vh]"
            )

    def _bind(key: str, transform: Any = lambda v: v) -> Any:
        def handler(e: Any) -> None:
            state[key] = transform(e.value)
            render_table.refresh()

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
