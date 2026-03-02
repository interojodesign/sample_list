"""Bootstrap wrapper for compiled app module."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from importlib.machinery import SourcelessFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parent
PYC_PATH = ROOT_DIR / "app_compiled.pyc"

if not PYC_PATH.exists():
    fallback = ROOT_DIR / "__pycache__" / "app.cpython-313.pyc"
    if fallback.exists():
        PYC_PATH = fallback
    else:
        raise FileNotFoundError(f"Compiled app not found: {PYC_PATH}")

loader = SourcelessFileLoader("_compiled_dashboard_app", str(PYC_PATH))
spec = spec_from_loader(loader.name, loader)
if spec is None:
    raise RuntimeError("Failed to create module spec for compiled app")

compiled_app = module_from_spec(spec)
compiled_app.__file__ = str(ROOT_DIR / "app.py")
loader.exec_module(compiled_app)

# Keep project-relative file paths stable.
if hasattr(compiled_app, "BASE_DIR"):
    compiled_app.BASE_DIR = ROOT_DIR
if hasattr(compiled_app, "LAST_FILE_RECORD"):
    compiled_app.LAST_FILE_RECORD = ROOT_DIR / ".last-used-file"


def _ensure_default_data_file_fallback() -> None:
    """Prefer sample-list.xlsx over implicit default CSV."""
    record_path = ROOT_DIR / ".last-used-file"
    default_csv = ROOT_DIR / "sample-list.csv"
    default_xlsx = ROOT_DIR / "sample-list.xlsx"
    if not default_xlsx.exists():
        return
    try:
        if record_path.exists():
            stored = record_path.read_text(encoding="utf-8").strip()
            if stored in {"sample-list.csv", "./sample-list.csv", ".\\sample-list.csv"}:
                record_path.write_text("sample-list.xlsx", encoding="utf-8")
                return
            if stored:
                stored_path = Path(stored)
                if not stored_path.is_absolute():
                    stored_path = ROOT_DIR / stored_path
                if stored_path.exists():
                    return
        if default_csv.exists():
            return
        record_path.write_text("sample-list.xlsx", encoding="utf-8")
    except Exception:
        # Non-fatal: app can still run with manual file selection.
        pass


_ensure_default_data_file_fallback()

if hasattr(compiled_app, "get_last_file_path"):
    _orig_get_last_file_path = compiled_app.get_last_file_path

    def _get_last_file_path_prefer_xlsx():
        preferred_xlsx = ROOT_DIR / "sample-list.xlsx"
        if preferred_xlsx.exists():
            return preferred_xlsx
        return _orig_get_last_file_path()

    compiled_app.get_last_file_path = _get_last_file_path_prefer_xlsx

if hasattr(compiled_app, "get_current_file_path"):
    _orig_get_current_file_path = compiled_app.get_current_file_path

    def _get_current_file_path_prefer_xlsx():
        path = _orig_get_current_file_path()
        preferred_xlsx = ROOT_DIR / "sample-list.xlsx"
        if not preferred_xlsx.exists():
            return path
        try:
            current_path = Path(path)
            if not current_path.is_absolute():
                current_path = ROOT_DIR / current_path
            if current_path.name.lower() == "sample-list.csv":
                return preferred_xlsx
        except Exception:
            return preferred_xlsx
        return path

    compiled_app.get_current_file_path = _get_current_file_path_prefer_xlsx

if hasattr(compiled_app, "init_state"):
    _orig_init_state = compiled_app.init_state

    def _init_state_prefer_xlsx(*args, **kwargs):
        result = _orig_init_state(*args, **kwargs)
        preferred_xlsx = ROOT_DIR / "sample-list.xlsx"
        if preferred_xlsx.exists():
            try:
                compiled_app.st.session_state["current_file"] = str(preferred_xlsx)
                (ROOT_DIR / ".last-used-file").write_text(
                    "sample-list.xlsx",
                    encoding="utf-8",
                )
            except Exception:
                pass
        return result

    compiled_app.init_state = _init_state_prefer_xlsx

# Open stage dialog only right after explicit "목록보기" click.
if hasattr(compiled_app, "set_query_params"):
    _orig_set_query_params = compiled_app.set_query_params

    def _set_query_params_with_stage_gate(**kwargs):
        try:
            if kwargs.get("view") == "sample" and kwargs.get("stage_idx") is not None:
                compiled_app.st.session_state["_stage_dialog_open_once"] = True
        except Exception:
            pass
        return _orig_set_query_params(**kwargs)

    compiled_app.set_query_params = _set_query_params_with_stage_gate

# Rename stage label globally.
_NEW_MISSING_STAGE_LABEL = "샘플 발송일 미확정"
_OLD_MISSING_STAGE_LABELS = {
    "납기예정일 미확정",
    "발송예정일 미설정",
    "발송일 미확정",
}
_STAGE_TONE_PALETTE = {
    # Muted, balanced palette: distinct but easy on the eyes.
    "샘플 발송일 미확정": "#A9CFAF",
    "대기": "#B4A8DE",
    "진행중": "#A9CFE0",
    "납기임박": "#E2C98C",
    "납기지연": "#DEA692",
    "보류": "#B4BCCB",
    "완료": "#D3D8E2",
}
_STATUS_HINT_TEXT = "오른쪽 목록보기 버튼을 클릭하면 해당 단계의 샘플 목록이 팝업으로 열립니다."


def _normalize_stage_label(value: str) -> str:
    text = str(value).strip()
    if text in _OLD_MISSING_STAGE_LABELS:
        return _NEW_MISSING_STAGE_LABEL
    return text


if hasattr(compiled_app, "STAGE_ORDER"):
    normalized_order = []
    for stage in list(getattr(compiled_app, "STAGE_ORDER", []) or []):
        mapped = _normalize_stage_label(stage)
        if mapped not in normalized_order:
            normalized_order.append(mapped)
    compiled_app.STAGE_ORDER = normalized_order

if hasattr(compiled_app, "STAGE_COLORS"):
    stage_colors = dict(getattr(compiled_app, "STAGE_COLORS", {}) or {})
    for old in _OLD_MISSING_STAGE_LABELS:
        stage_colors.pop(old, None)
    stage_colors.update(_STAGE_TONE_PALETTE)
    compiled_app.STAGE_COLORS = stage_colors

if hasattr(compiled_app, "determine_stage"):
    _orig_determine_stage = compiled_app.determine_stage

    def _determine_stage_renamed(*args, **kwargs):
        return _normalize_stage_label(_orig_determine_stage(*args, **kwargs))

    compiled_app.determine_stage = _determine_stage_renamed

if hasattr(compiled_app, "build_duration_entries") and hasattr(compiled_app, "pd"):
    _orig_build_duration_entries = compiled_app.build_duration_entries
    _pd = compiled_app.pd

    def _build_duration_entries_with_earliest_start(df):
        try:
            if df is None or getattr(df, "empty", True):
                return []
            local = df.copy()
            columns = set(local.columns)

            confirm_col = "시안 컨펌일" if "시안 컨펌일" in columns else None
            print_start_col = "인쇄 시작일" if "인쇄 시작일" in columns else None

            end_col = None
            for candidate in ("발송 예정일", "시안 발송일", "발송일"):
                if candidate in columns:
                    end_col = candidate
                    break

            if end_col is None:
                return _orig_build_duration_entries(df)

            end_series = _pd.to_datetime(local[end_col], errors="coerce")
            start_candidates = []
            if confirm_col is not None:
                start_candidates.append(_pd.to_datetime(local[confirm_col], errors="coerce"))
            if print_start_col is not None:
                start_candidates.append(_pd.to_datetime(local[print_start_col], errors="coerce"))

            if not start_candidates:
                return _orig_build_duration_entries(df)

            start_frame = _pd.concat(start_candidates, axis=1)
            start_series = start_frame.min(axis=1, skipna=True)

            valid_mask = start_series.notna() & end_series.notna()
            if not valid_mask.any():
                return []

            local = local.loc[valid_mask].copy()
            start_series = start_series.loc[valid_mask]
            end_series = end_series.loc[valid_mask]

            durations = (end_series - start_series).dt.days
            valid_duration_mask = durations.notna()
            local = local.loc[valid_duration_mask].copy()
            start_series = start_series.loc[valid_duration_mask]
            end_series = end_series.loc[valid_duration_mask]
            durations = durations.loc[valid_duration_mask].clip(lower=0)

            entries = []
            for idx in local.index:
                entries.append(
                    {
                        "start": start_series.loc[idx],
                        "end": end_series.loc[idx],
                        "days": int(durations.loc[idx]),
                    }
                )
            entries.sort(key=lambda item: item.get("start"))
            return entries
        except Exception:
            return _orig_build_duration_entries(df)

    compiled_app.build_duration_entries = _build_duration_entries_with_earliest_start

if hasattr(compiled_app, "go") and hasattr(compiled_app.go, "Figure"):
    _orig_figure_add_annotation = compiled_app.go.Figure.add_annotation

    def _add_annotation_without_total_count(self, *args, **kwargs):
        text = kwargs.get("text")
        if text is None and args and isinstance(args[0], dict):
            text = args[0].get("text")
        plain = re.sub(r"<[^>]+>", "", str(text or "")).strip()
        if re.fullmatch(r"총\s*\d+\s*건", plain):
            return self
        return _orig_figure_add_annotation(self, *args, **kwargs)

    compiled_app.go.Figure.add_annotation = _add_annotation_without_total_count


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(base: date, months: int) -> date:
    month_idx = (base.month - 1) + months
    year = base.year + month_idx // 12
    month = month_idx % 12 + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _period_bounds(anchor: date, period_choice: str) -> tuple[date, date]:
    if period_choice == "주간":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period_choice == "월별":
        start = date(anchor.year, anchor.month, 1)
        return start, _month_end(anchor.year, anchor.month)
    if period_choice == "분기별":
        quarter_start_month = ((anchor.month - 1) // 3) * 3 + 1
        start = date(anchor.year, quarter_start_month, 1)
        end_month = quarter_start_month + 2
        return start, _month_end(anchor.year, end_month)
    if period_choice == "반기별":
        start_month = 1 if anchor.month <= 6 else 7
        start = date(anchor.year, start_month, 1)
        end_month = 6 if start_month == 1 else 12
        return start, _month_end(anchor.year, end_month)
    if period_choice == "년도별":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    return anchor, anchor


def _shift_period_range(
    start_date: date,
    end_date: date,
    period_choice: str,
    step: int,
) -> tuple[date, date]:
    _ = end_date
    if period_choice == "주간":
        shifted_anchor = start_date + timedelta(days=7 * step)
        return _period_bounds(shifted_anchor, period_choice)

    month_steps = {
        "월별": 1,
        "분기별": 3,
        "반기별": 6,
        "년도별": 12,
    }.get(period_choice, 0)
    if month_steps > 0:
        shifted_anchor = _add_months(start_date, month_steps * step)
        return _period_bounds(shifted_anchor, period_choice)
    return start_date, end_date


if hasattr(compiled_app, "render_period_selector") and hasattr(compiled_app, "FILTER_PRESETS"):
    def _render_period_selector_with_arrows(today: datetime, key_prefix: str):
        st = compiled_app.st
        presets = compiled_app.FILTER_PRESETS
        period_options = list(presets.keys())
        period_key = f"{key_prefix}_period"
        range_key = f"{key_prefix}_date_range"
        pending_key = f"{key_prefix}_pending_date_range"
        period_sync_key = f"{key_prefix}_period_sync"

        toolbar = st.container(key=f"period_toolbar_{key_prefix}")
        with toolbar:
            label_col, input_col, prev_col, next_col, mode_col = st.columns(
                [0.62, 2.55, 0.18, 0.18, 2.85],
                gap="small",
            )

            label_col.markdown(
                "<p class='period-inline-label'>기간 조회</p>",
                unsafe_allow_html=True,
            )

            with mode_col:
                period_choice = st.radio(
                    "조회 범위",
                    period_options,
                    horizontal=True,
                    index=1,
                    label_visibility="collapsed",
                    key=period_key,
                )

            preset_start, preset_end = presets[period_choice](today)
            default_start = preset_start.date()
            default_end = preset_end.date()

            pending_range = st.session_state.pop(pending_key, None)
            if pending_range is not None:
                st.session_state[range_key] = tuple(map(_as_date, pending_range))
                st.session_state[period_sync_key] = period_choice
            else:
                if range_key not in st.session_state:
                    st.session_state[range_key] = (default_start, default_end)
                    st.session_state[period_sync_key] = period_choice
                elif st.session_state.get(period_sync_key) != period_choice:
                    # Reset only when period mode changes.
                    st.session_state[range_key] = (default_start, default_end)
                    st.session_state[period_sync_key] = period_choice

            with input_col:
                selected_range = st.date_input(
                    "기간 조회",
                    key=range_key,
                    label_visibility="collapsed",
                )

            with prev_col:
                prev_clicked = st.button(
                    "◀",
                    key=f"period_nav_prev_{key_prefix}",
                    help="이전 기간",
                    use_container_width=True,
                )
            with next_col:
                next_clicked = st.button(
                    "▶",
                    key=f"period_nav_next_{key_prefix}",
                    help="다음 기간",
                    use_container_width=True,
                )

            if isinstance(selected_range, tuple) and len(selected_range) == 2:
                manual_start, manual_end = selected_range
            elif isinstance(selected_range, list) and len(selected_range) == 2:
                manual_start, manual_end = selected_range[0], selected_range[1]
            else:
                manual_start = selected_range
                manual_end = selected_range

            manual_start = _as_date(manual_start)
            manual_end = _as_date(manual_end)
            if manual_start > manual_end:
                st.warning("시작일이 종료일보다 늦을 수 없습니다.")
                st.stop()

            if prev_clicked or next_clicked:
                step = -1 if prev_clicked else 1
                new_start, new_end = _shift_period_range(
                    manual_start,
                    manual_end,
                    period_choice,
                    step,
                )
                st.session_state[pending_key] = (new_start, new_end)
                st.session_state[period_sync_key] = period_choice
                st.rerun()

            shortcut_items = [
                ("당월", "this_month"),
                ("당분기", "this_quarter"),
                ("당반기", "this_half"),
                ("올해", "this_year"),
                ("작년", "last_year"),
                ("2개년", "last_2_years"),
                ("3개년", "last_3_years"),
                ("최대기간", "max_period"),
            ]
            shortcut_area, _ = st.columns([6, 2], gap="small")
            with shortcut_area:
                shortcut_cols = st.columns(len(shortcut_items), gap="small")

            selected_shortcut = ""
            for idx, (label, shortcut_key) in enumerate(shortcut_items):
                if shortcut_cols[idx].button(
                    label,
                    key=f"period_shortcut_{key_prefix}_{shortcut_key}",
                    use_container_width=True,
                ):
                    selected_shortcut = shortcut_key

            shortcut_range = compiled_app.resolve_period_shortcut(selected_shortcut, today)
            if selected_shortcut == "max_period" and shortcut_range is None:
                st.info("발송 예정일 기준 데이터가 없어 최대기간을 계산할 수 없습니다.")
            elif shortcut_range is not None:
                s_dt, e_dt = shortcut_range
                s_date = _as_date(s_dt)
                e_date = _as_date(e_dt)
                st.session_state[pending_key] = (s_date, e_date)
                st.session_state[period_sync_key] = period_choice
                st.rerun()

        final_start = datetime.combine(manual_start, datetime.min.time())
        final_end = datetime.combine(manual_end, datetime.max.time())
        return period_choice, final_start, final_end

    compiled_app.render_period_selector = _render_period_selector_with_arrows

# Force bold value labels on bar charts before rendering.
if hasattr(compiled_app, "render_chart_card"):
    _orig_render_chart_card = compiled_app.render_chart_card

    def _strip_total_from_bar_text(value):
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            return text
        plain = re.sub(r"<[^>]+>", " ", text).replace("\n", " ")
        plain = re.sub(r"\s+", " ", plain).strip()
        if not re.search(r"총\s*\d+\s*건", plain):
            return value
        plain = re.sub(r"총\s*\d+\s*건", "", plain).strip()
        match = re.search(r"\d+\s*건", plain)
        return match.group(0) if match else ""

    def _to_sequence(value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            return [value]
        try:
            return list(value)
        except Exception:
            return [value]

    def _render_chart_card_with_bold_labels(fig, *args, **kwargs):
        try:
            has_bar_trace = False
            for trace in list(getattr(fig, "data", []) or []):
                try:
                    trace_type = getattr(trace, "type", "")
                    text_values = getattr(trace, "text", None)
                    if isinstance(text_values, (list, tuple)):
                        trace.text = [_strip_total_from_bar_text(v) for v in text_values]
                    elif text_values is not None:
                        seq = _to_sequence(text_values)
                        trace.text = (
                            [_strip_total_from_bar_text(v) for v in seq]
                            if len(seq) > 1
                            else _strip_total_from_bar_text(text_values)
                        )

                    if trace_type != "bar":
                        continue

                    has_bar_trace = True
                    y_values = _to_sequence(getattr(trace, "y", None))
                    trace.text = [
                        f"{int(v)}건" if str(v).strip() and int(v) > 0 else ""
                        for v in y_values
                    ]
                    trace.texttemplate = "<b>%{text}</b>"
                    if getattr(trace, "textfont", None):
                        current_size = getattr(trace.textfont, "size", 13) or 13
                        trace.textfont.size = max(13, int(current_size))
                    else:
                        trace.textfont = dict(size=13, color="#0f172a")
                except Exception:
                    continue

            # Remove in-chart total annotation like "총 29건".
            if has_bar_trace:
                kept_annotations = []
                for ann in list(getattr(fig.layout, "annotations", []) or []):
                    ann_text = getattr(ann, "text", "")
                    plain_text = re.sub(r"<[^>]+>", "", str(ann_text)).strip()
                    if re.search(r"총\s*\d+\s*건", plain_text):
                        continue
                    kept_annotations.append(ann)
                fig.update_layout(annotations=kept_annotations)

            title = kwargs.get("title")
            plain_title = re.sub(r"<[^>]+>", "", str(title or "")).strip()
            is_main_stage_chart = isinstance(title, str) and "샘플 종합 진도 현황" in title
            is_detail_stage_chart = bool(plain_title) and (
                plain_title.endswith("단계별 현황") or plain_title.endswith("샘플 현황")
            )
            if is_main_stage_chart or is_detail_stage_chart:
                total_count = 0
                max_stage_count = 0
                for trace in list(getattr(fig, "data", []) or []):
                    if getattr(trace, "type", "") != "bar":
                        continue
                    # Rename x-axis label for the missing-shipment bucket.
                    try:
                        x_values = _to_sequence(getattr(trace, "x", None))
                        trace.x = [
                            "발송일 미확정"
                            if str(v).strip() in {"미확정", "발송일 미확정", "샘플 발송일 미확정", _NEW_MISSING_STAGE_LABEL}
                            else v
                            for v in x_values
                        ]
                    except Exception:
                        pass
                    y_values = _to_sequence(getattr(trace, "y", None))
                    for v in y_values:
                        try:
                            int_value = int(v)
                        except Exception:
                            continue
                        total_count += int_value
                        max_stage_count = max(max_stage_count, int_value)
                    # Force bar labels to count-only text (e.g., "17건"), removing any extra phrases.
                    try:
                        trace.text = [
                            f"{int(v)}건" if str(v).strip() and int(v) > 0 else ""
                            for v in y_values
                        ]
                    except Exception:
                        pass
                # Keep missing-shipment category pinned to the far left.
                try:
                    category_order = []
                    for stage in list(getattr(compiled_app, "STAGE_ORDER", []) or []):
                        stage_label = _normalize_stage_label(stage)
                        if stage_label == _NEW_MISSING_STAGE_LABEL:
                            stage_label = "발송일 미확정"
                        if stage_label not in category_order:
                            category_order.append(stage_label)
                    if category_order:
                        fig.update_xaxes(
                            categoryorder="array",
                            categoryarray=category_order,
                        )
                except Exception:
                    pass
                # Keep labels at original position; lift only the baseline (y=0) upward.
                try:
                    # Keep a consistent baseline ratio across factories and the main chart.
                    line_lift = (max_stage_count * 0.05) if max_stage_count else 0.2
                    y_top = max(1.0, max_stage_count * 1.08)
                    fig.update_yaxes(
                        range=[-line_lift, y_top],
                        zeroline=True,
                        zerolinecolor="#111827",
                        zerolinewidth=1.2,
                    )
                    fig.update_xaxes(
                        showline=False,
                        tickangle=0,
                        ticklabelposition="outside",
                        ticklabelstandoff=0,
                        automargin=True,
                    )
                except Exception:
                    pass
                base_title = plain_title
                if is_main_stage_chart and total_count > 0:
                    kwargs["title"] = (
                        "<span style='font-size:0.94rem;font-weight:700;color:#4b5563;'>"
                        f"{base_title} (총 {total_count}건)"
                        "</span>"
                    )
        except Exception:
            pass
        return _orig_render_chart_card(fig, *args, **kwargs)

    compiled_app.render_chart_card = _render_chart_card_with_bold_labels

if hasattr(compiled_app, "render_sample_dashboard"):
    _orig_render_sample_dashboard = compiled_app.render_sample_dashboard

    def _render_sample_dashboard_with_hint_relocated():
        st_obj = compiled_app.st
        original_caption = st_obj.caption
        suppressed_hint = {"value": False}

        def _caption_override(body=None, *args, **kwargs):
            if str(body or "").strip() == _STATUS_HINT_TEXT:
                suppressed_hint["value"] = True
                return None
            return original_caption(body, *args, **kwargs)

        st_obj.caption = _caption_override
        try:
            result = _orig_render_sample_dashboard()
        finally:
            st_obj.caption = original_caption

        if suppressed_hint["value"]:
            _, right_col = st_obj.columns([1.35, 0.95])
            with right_col:
                st_obj.markdown(
                    (
                        "<div style='margin-top:-12px;color:#6b7280;font-size:0.9rem;"
                        "line-height:1.45;'>"
                        f"{_STATUS_HINT_TEXT}"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
        return result

    compiled_app.render_sample_dashboard = _render_sample_dashboard_with_hint_relocated

# Force C/S/FRP detail page chart layout without relying on runtime DOM class injection.
if hasattr(compiled_app, "render_factory_detail_page"):
    _orig_render_factory_detail_page = compiled_app.render_factory_detail_page

    def _render_factory_detail_page_with_fixed_stage_width(factory_name):
        st_obj = compiled_app.st
        orig_columns = st_obj.columns
        orig_render_chart_card = getattr(compiled_app, "render_chart_card", None)
        orig_render_duration_trend_chart = getattr(compiled_app, "render_duration_trend_chart", None)
        chart_row_adjusted = False

        def _columns_override(spec, *args, **kwargs):
            nonlocal chart_row_adjusted
            # In factory detail rendering, the only st.columns(2) call is the stage/trend chart row.
            if spec == 2 and not chart_row_adjusted:
                chart_row_adjusted = True
                return orig_columns([1.48, 1.22], *args, **kwargs)
            return orig_columns(spec, *args, **kwargs)

        def _render_chart_card_override(fig, *args, **kwargs):
            title = kwargs.get("title") or ""
            plain_title = re.sub(r"<[^>]+>", "", str(title)).strip()
            if plain_title.endswith("단계별 현황"):
                # Match the same geometry as "샘플 종합 진도 현황".
                kwargs["title"] = re.sub(r"단계별 현황$", "샘플 현황", plain_title)
                kwargs["card_width"] = None
                kwargs["chart_width"] = 670
                kwargs["chart_height"] = 298
                try:
                    fig.update_layout(
                        margin=dict(l=22, r=8, t=10, b=34),
                    )
                    fig.update_xaxes(automargin=True)
                    fig.update_yaxes(automargin=True)
                except Exception:
                    pass
            if "소요일 추이" in plain_title:
                # Prevent clipping in the narrower right column.
                kwargs["card_width"] = None
                kwargs["chart_width"] = 500
                kwargs["chart_height"] = 298
                try:
                    pd_obj = getattr(compiled_app, "pd", None)
                    parsed_x = []
                    parsed_end = []
                    parsed_y = []
                    points = []
                    if pd_obj is not None:
                        for trace in list(getattr(fig, "data", []) or []):
                            x_seq = _to_sequence(getattr(trace, "x", None))
                            y_seq = _to_sequence(getattr(trace, "y", None))
                            for x_val in x_seq:
                                ts = pd_obj.to_datetime(x_val, errors="coerce")
                                if not pd_obj.isna(ts):
                                    parsed_x.append(ts)
                            pair_len = min(len(x_seq), len(y_seq))
                            for i in range(pair_len):
                                ts_point = pd_obj.to_datetime(x_seq[i], errors="coerce")
                                if pd_obj.isna(ts_point):
                                    continue
                                try:
                                    y_point = float(y_seq[i])
                                except Exception:
                                    continue
                                points.append((ts_point, y_point))
                            for end_val in _to_sequence(getattr(trace, "customdata", None)):
                                candidate = end_val
                                if isinstance(end_val, (list, tuple)) and end_val:
                                    candidate = end_val[0]
                                ts_end = pd_obj.to_datetime(candidate, errors="coerce")
                                if not pd_obj.isna(ts_end):
                                    parsed_end.append(ts_end)
                            for y_val in _to_sequence(getattr(trace, "y", None)):
                                try:
                                    parsed_y.append(float(y_val))
                                except Exception:
                                    continue

                    x_range = None
                    tick_vals = None
                    tick_text = None
                    if parsed_x and pd_obj is not None:
                        anchors = list(parsed_x)
                        if parsed_end:
                            anchors.extend(parsed_end)
                        latest = max(anchors)
                        latest_month_start = pd_obj.Timestamp(latest.year, latest.month, 1)
                        reference_month_start = latest_month_start
                        try:
                            range_ends = []
                            for key, value in dict(getattr(st_obj, "session_state", {}) or {}).items():
                                if "date_range" not in str(key):
                                    continue
                                if isinstance(value, (list, tuple)) and len(value) == 2:
                                    end_value = value[1] if value[1] is not None else value[0]
                                    ts_end = pd_obj.to_datetime(end_value, errors="coerce")
                                    if not pd_obj.isna(ts_end):
                                        range_ends.append(ts_end)
                            if range_ends:
                                selected_end = max(range_ends)
                                selected_month_start = pd_obj.Timestamp(selected_end.year, selected_end.month, 1)
                                if selected_month_start > reference_month_start:
                                    reference_month_start = selected_month_start
                        except Exception:
                            pass
                        try:
                            now_ts = pd_obj.Timestamp.now()
                            now_month_start = pd_obj.Timestamp(now_ts.year, now_ts.month, 1)
                            if now_month_start > reference_month_start:
                                reference_month_start = now_month_start
                        except Exception:
                            pass
                        window_start = reference_month_start - pd_obj.DateOffset(months=2)
                        window_end = reference_month_start + pd_obj.offsets.MonthEnd(1)
                        tick_vals = [window_start + pd_obj.DateOffset(months=i) for i in range(3)]
                        tick_text = [f"{ts.year}년 {ts.month:02d}월" for ts in tick_vals]
                        # Nudge month labels slightly further right for visual centering.
                        x_range = [window_start - pd_obj.Timedelta(days=18), window_end]

                    y_top = None
                    y_lift = None
                    if parsed_y:
                        y_max = max(parsed_y)
                        # Keep enough headroom so labels don't collide with the average text line.
                        y_top = max(1.0, y_max * 1.24)
                        y_lift = y_max * 0.05 if y_max > 0 else 0.2

                    fig.update_layout(
                        # Match chart card inner spacing with the left "샘플 현황" chart.
                        margin=dict(l=22, r=8, t=22, b=28),
                        xaxis_title=None,
                        yaxis_title=None,
                    )
                    fig.update_xaxes(
                        tickmode="array" if tick_vals else None,
                        tickvals=tick_vals,
                        ticktext=tick_text,
                        tickangle=0,
                        title_text=None,
                        range=x_range,
                        showline=False,
                        ticklabelposition="outside",
                        ticklabelstandoff=0,
                        automargin=True,
                    )
                    fig.update_yaxes(
                        title_text=None,
                        range=[-(y_lift or 0.2), y_top] if y_top is not None else None,
                        zeroline=True,
                        zerolinecolor="#111827",
                        zerolinewidth=1.2,
                        showgrid=True,
                        gridcolor="#eef2f7",
                        ticklabelposition="outside",
                        ticklabelstandoff=0,
                        ticks="",
                        tickfont=dict(size=11, color="#111827"),
                        automargin=False,
                    )
                    fig.update_traces(
                        cliponaxis=False,
                        textposition="top center",
                    )

                    # Show monthly average duration directly below the trend chart title.
                    if pd_obj is not None and tick_vals:
                        # Remove stale monthly-average annotations before re-adding.
                        kept_anns = []
                        for ann in list(getattr(fig.layout, "annotations", []) or []):
                            ann_text = re.sub(r"<[^>]+>", "", str(getattr(ann, "text", "")))
                            if "월별 평균 소요일" in ann_text:
                                continue
                            kept_anns.append(ann)
                        fig.update_layout(annotations=kept_anns)

                        avg_by_month = {}
                        for ts_point, y_point in points:
                            key = f"{ts_point.year:04d}-{ts_point.month:02d}"
                            avg_by_month.setdefault(key, []).append(y_point)
                        avg_lines = []
                        for month_start in tick_vals:
                            key = f"{month_start.year:04d}-{month_start.month:02d}"
                            vals = avg_by_month.get(key, [])
                            if vals:
                                avg_value = sum(vals) / len(vals)
                                avg_days = int(round(avg_value))
                            else:
                                avg_days = 0
                            yy = str(month_start.year)[-2:]
                            avg_lines.append(f"{yy}년{month_start.month:02d}월 : {avg_days}일")
                        avg_inline = " / ".join(avg_lines)
                        kwargs["title"] = "샘플 제작 소요일 추이"
                        fig.add_annotation(
                            xref="paper",
                            yref="paper",
                            x=0.0,
                            y=1.03,
                            xanchor="left",
                            yanchor="bottom",
                            showarrow=False,
                            align="left",
                            text=f"<b>월별 평균 소요일</b> {avg_inline}",
                            font=dict(size=9, color="#334155"),
                            bgcolor="rgba(0,0,0,0)",
                            borderwidth=0,
                        )
                except Exception:
                    pass
            return orig_render_chart_card(fig, *args, **kwargs)

        def _render_duration_trend_chart_override(shipment_entries, *, width=760, card_width=None):
            filtered_entries = list(shipment_entries or [])
            pd_obj = getattr(compiled_app, "pd", None)
            if filtered_entries and pd_obj is not None:
                parsed_starts = []
                for item in filtered_entries:
                    ts = pd_obj.to_datetime(item.get("start"), errors="coerce")
                    if not pd_obj.isna(ts):
                        parsed_starts.append(ts)
                if parsed_starts:
                    max_start = max(parsed_starts)
                    max_month_start = pd_obj.Timestamp(max_start.year, max_start.month, 1)
                    min_start = max_month_start - pd_obj.DateOffset(months=2)
                    max_end = max_month_start + pd_obj.offsets.MonthEnd(1)
                    recent_only = []
                    for item in filtered_entries:
                        ts = pd_obj.to_datetime(item.get("start"), errors="coerce")
                        if pd_obj.isna(ts):
                            continue
                        if min_start <= ts <= max_end:
                            recent_only.append(item)
                    if recent_only:
                        filtered_entries = recent_only

            adjusted_width = min(int(width), 500)
            return orig_render_duration_trend_chart(
                filtered_entries,
                width=adjusted_width,
                card_width=None,
            )

        st_obj.columns = _columns_override
        if callable(orig_render_chart_card):
            compiled_app.render_chart_card = _render_chart_card_override
        if callable(orig_render_duration_trend_chart):
            compiled_app.render_duration_trend_chart = _render_duration_trend_chart_override
        try:
            return _orig_render_factory_detail_page(factory_name)
        finally:
            st_obj.columns = orig_columns
            if callable(orig_render_chart_card):
                compiled_app.render_chart_card = orig_render_chart_card
            if callable(orig_render_duration_trend_chart):
                compiled_app.render_duration_trend_chart = orig_render_duration_trend_chart

    compiled_app.render_factory_detail_page = _render_factory_detail_page_with_fixed_stage_width

# Final safety net: strip duplicated "총 N건" labels from Plotly HTML payload.
if hasattr(compiled_app, "components") and hasattr(compiled_app.components, "html"):
    _orig_components_html = compiled_app.components.html

    def _components_html_without_total_duplicates(html_str, *args, **kwargs):
        try:
            if isinstance(html_str, str) and "plotly" in html_str:
                marker = "Plotly.newPlot"
                split_idx = html_str.find(marker)
                if split_idx >= 0:
                    prefix = html_str[:split_idx]
                    script_part = html_str[split_idx:]
                    # Strip any in-plot total text while keeping title area text outside plot payload.
                    script_part = re.sub(r"총\\s*\\d+\\s*건\\s*<br>\\s*", "", script_part)
                    script_part = re.sub(r"총\\s*\\d+\\s*건\\\\n", "", script_part)
                    script_part = re.sub(r"총\\s*\\d+\\s*건", "", script_part)
                    html_str = prefix + script_part
                else:
                    html_str = re.sub(r"총\\s*\\d+\\s*건", "", html_str)
        except Exception:
            pass
        return _orig_components_html(html_str, *args, **kwargs)

    compiled_app.components.html = _components_html_without_total_duplicates


def _inject_runtime_dom_tweaks() -> None:
    # Intentionally no-op: DOM tweaks disabled in favor of render-level adjustments.
    return

if hasattr(compiled_app, "main"):
    try:
        allow_once = bool(compiled_app.st.session_state.pop("_stage_dialog_open_once", False))
        if not allow_once and "stage_idx" in compiled_app.st.query_params:
            kept = {k: v for k, v in compiled_app.st.query_params.items() if k not in {"stage_idx"}}
            if str(kept.get("nav", "")) == "0":
                kept.pop("nav", None)
            compiled_app.st.query_params.clear()
            for key, value in kept.items():
                compiled_app.st.query_params[key] = value
    except Exception:
        pass
    compiled_app.main()
    _inject_runtime_dom_tweaks()
else:
    raise AttributeError("Compiled app module has no main()")
