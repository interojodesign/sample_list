"""Streamlit 기반 샘플 리스트 관리 도구."""

from __future__ import annotations

import io
from pathlib import Path
from datetime import datetime, timedelta
from collections import OrderedDict
import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from urllib.parse import urlencode


st.set_page_config(
    page_title="샘플 리스트 관리자",
    page_icon="📋",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent
LAST_FILE_RECORD = BASE_DIR / ".last-used-file"
SELECTION_COLUMN = "__row_select__"
SELECTION_LABEL = "행 선택"
HISTORY_LIMIT = 30
LOCATION_COLUMN = "샘플제작 공장위치"
LOCATION_CANDIDATE_COLUMNS = [
    LOCATION_COLUMN,
    "샘플 제작공장위치",
    "샘플제작공장위치",
]
LOCATION_DISPLAY_ORDER = ["C관", "S관", "FRP"]

def normalize_dia_value(value: str) -> str:
    text = str(value).replace("\\n", "\n").strip()
    combo_aliases = {
        "14.2\n14.5",
        "14.2 14.5",
        "14.2 + 14.5",
        "14.2+14.5",
        "14.2\n14.5\n",
    }
    if text in combo_aliases:
        return "14.2\n14.5"
    return text


def normalize_cell_value(column: str, value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "-"}:
        return ""
    if column == "DIA":
        return normalize_dia_value(text)
    normalized_select = normalize_select_option(column, text)
    if normalized_select is not None:
        return normalized_select
    return text


def canonical_select_key(column: str, text: str) -> str:
    if not text:
        return ""
    key = text.strip()
    lowered = key.lower()
    if lowered in {"none", "null", "nan", "-"}:
        return ""
    if column == "함수율":
        key = key.replace(" ", "").replace("%", "")
        try:
            value = float(key)
            if value <= 1:
                value *= 100
            key = str(int(round(value)))
        except ValueError:
            pass
        return key
    if column in {"샘플 구분", "착용기간"}:
        return key.replace(" ", "").upper()
    if column == "렌즈 구분":
        return key.replace(" ", "").upper()
    if column == "제작 현황":
        return lowered
    if column == "잉크 구분":
        return lowered
    return "".join(key.split()).lower()


def normalize_select_option(column: str, text: str) -> str | None:
    options = SELECT_COLUMN_OPTIONS.get(column)
    if not options:
        return None
    key = canonical_select_key(column, text)
    if not key:
        return ""
    for option in options:
        if not option:
            continue
        if canonical_select_key(column, option) == key:
            return option
    return text


SELECT_COLUMN_OPTIONS = {
    "렌즈 구분": ["", "SPH", "TORIC", "프리즘"],
    "샘플 구분": ["", "1D", "M", "ID"],
    "함수율": ["", "38%", "43%", "45%", "55%"],
    "DIA": ["", "14.2", "14.5", "14.2\n14.5"],
    "착용기간": ["", "1D", "M"],
    "잉크 구분": ["", "액상", "파우더"],
    "제작 현황": ["", "대기", "진행중", "완료", "Drop"],
}
STAGE_ORDER = ["대기", "진행중", "납기임박", "납기지연", "보류", "완료"]
STAGE_COLORS = {
    "대기": "#8b7edb",
    "진행중": "#51b2ce",
    "납기임박": "#e59b3a",
    "납기지연": "#e36c5c",
    "보류": "#7a8a9f",
    "완료": "#c3cbd9",
}


def parse_date(value: str | datetime | pd.Timestamp | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null", "-"}:
        return None
    for fmt in ("%y.%m.%d", "%Y.%m.%d", "%Y-%m-%d", "%y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.year < 2000:
                dt = dt.replace(year=dt.year + 2000)
            return dt
        except ValueError:
            continue
    try:
        return pd.to_datetime(text).to_pydatetime()
    except (ValueError, TypeError):
        return None


def determine_stage(row: pd.Series, today: datetime) -> str:
    raw = (row.get("제작 현황") or "").strip()
    lowered = raw.lower()
    if "대기" in raw or "waiting" in lowered:
        return "대기"
    if "완료" in raw or "complete" in lowered:
        return "완료"
    if "drop" in lowered or "보류" in raw:
        return "보류"
    if "진행" in raw:
        return "진행중"
    due_date = parse_date(row.get("납기 요청일") or row.get("배송/예정일"))
    if due_date is not None:
        delta = (due_date - today).days
        if delta < 0:
            return "납기지연"
        if delta <= 3:
            return "납기임박"
    return "진행중"
    due_date = parse_date(row.get("납기 요청일") or row.get("배송/예정일"))
    if due_date is not None:
        delta = (due_date - today).days
        if delta < 0:
            return "납기지연"
        if delta <= 3:
            return "납기임박"
    return "진행중"

DEFAULT_ROW = {
    "국가": "일본",
    "고객사": "Sincere",
    "담당자": "송미정 대리",
    "렌즈 구분": "SPH",
    "샘플 구분": "ID",
    "함수율": "45%",
    "DIA": "14.2",
    "잉크 구분": "색상",
    "품명": "실리콘 제한 렌즈 2종",
    "차수": "2",
    "샘플 접수일": "25.10.02",
    "시안 컨펌일": "25.10.04",
    "인쇄 시작일": "25.10.04",
    "인쇄 완료일": "25.10.08",
    "후공정 완성일": "25.10.09",
    "납기 요청일": "25.10.09",
    "배송/예정일": "25.10.10",
    "제작 현황": "대기",
}


def init_state() -> None:
    if "df" not in st.session_state:
        st.session_state.df = pd.DataFrame([DEFAULT_ROW])
    if "current_file" not in st.session_state:
        st.session_state.current_file = "sample-list.csv"
    if "status" not in st.session_state:
        st.session_state.status = "새 문서"
    if "last_uploaded_sig" not in st.session_state:
        st.session_state.last_uploaded_sig = None
    if "bootstrapped_from_file" not in st.session_state:
        st.session_state.bootstrapped_from_file = False
    if "row_selection" not in st.session_state:
        st.session_state.row_selection = [False] * len(st.session_state.df)
    ensure_row_selection_length()


def inject_app_styles() -> None:
    css_path = BASE_DIR / "styles.css"
    if css_path.exists():
        try:
            st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)
        except Exception:
            pass


def remember_last_file(path: Path) -> None:
    try:
        LAST_FILE_RECORD.write_text(path.name, encoding="utf-8")
    except OSError:
        pass


def get_last_file_path() -> Path | None:
    try:
        stored = LAST_FILE_RECORD.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not stored:
        return None
    candidate = BASE_DIR / stored
    return candidate if candidate.exists() else None


def bootstrap_from_last_file() -> None:
    if st.session_state.bootstrapped_from_file:
        return
    st.session_state.bootstrapped_from_file = True
    last_path = get_last_file_path()
    if not last_path:
        return
    try:
        st.session_state.df = load_local_file(last_path)
    except Exception as exc:
        st.warning(f"'{last_path.name}' 자동 불러오기 실패: {exc}")
        return
    st.session_state.current_file = last_path.name
    st.session_state.status = f"{last_path.name} 자동 불러오기 완료"
    st.session_state.last_uploaded_sig = None
    reset_history()


def ensure_row_selection_length() -> None:
    selection = st.session_state.get("row_selection", [])
    desired = len(st.session_state.df)
    if len(selection) < desired:
        selection = selection + [False] * (desired - len(selection))
    elif len(selection) > desired:
        selection = selection[:desired]
    st.session_state.row_selection = selection


def record_history_snapshot(force: bool = False) -> None:
    history: list[pd.DataFrame] = st.session_state.get("history", [])
    if history and not isinstance(history[0], pd.DataFrame):
        normalize_history_storage()
        history = st.session_state.get("history", [])

    snapshot = snapshot_dataframe(st.session_state.df)
    index: int = st.session_state.get("history_index", -1)

    if not history:
        st.session_state.history = [snapshot]
        st.session_state.history_index = 0
        return

    if (
        not force
        and 0 <= index < len(history)
        and history[index].equals(snapshot)
    ):
        return

    trimmed = history[: index + 1] if 0 <= index else history
    trimmed.append(snapshot)
    if len(trimmed) > HISTORY_LIMIT:
        trimmed = trimmed[-HISTORY_LIMIT:]
    st.session_state.history = trimmed
    st.session_state.history_index = len(trimmed) - 1


def reset_history() -> None:
    st.session_state.history = []
    st.session_state.history_index = -1
    record_history_snapshot(force=True)


def ensure_history_initialized() -> None:
    if "history" not in st.session_state or "history_index" not in st.session_state:
        st.session_state.history = []
        st.session_state.history_index = -1
    normalize_history_storage()
    if not st.session_state.history:
        record_history_snapshot(force=True)


def normalize_history_storage() -> None:
    history = st.session_state.get("history")
    if not history:
        return
    if isinstance(history[0], pd.DataFrame):
        return

    converted: list[pd.DataFrame] = []
    for entry in history:
        if isinstance(entry, pd.DataFrame):
            converted.append(snapshot_dataframe(entry))
            continue
        if isinstance(entry, str):
            try:
                df = pd.read_json(io.StringIO(entry), orient="split")
            except Exception:
                continue
            converted.append(snapshot_dataframe(sanitize_dataframe(df)))
            continue
    if converted:
        st.session_state.history = converted
        st.session_state.history_index = min(
            st.session_state.get("history_index", len(converted) - 1),
            len(converted) - 1,
        )
    else:
        st.session_state.history = []
        st.session_state.history_index = -1


def can_undo() -> bool:
    return st.session_state.get("history_index", 0) > 0


def can_redo() -> bool:
    history = st.session_state.get("history", [])
    index = st.session_state.get("history_index", 0)
    return 0 <= index < len(history) - 1


def apply_history_snapshot(target_index: int, message: str) -> None:
    history: list[pd.DataFrame] = st.session_state.get("history", [])
    if not history or not (0 <= target_index < len(history)):
        return
    restored = copy_from_snapshot(history[target_index])
    st.session_state.df = sanitize_dataframe(restored)
    st.session_state.history_index = target_index
    st.session_state.row_selection = [False] * len(st.session_state.df)
    st.session_state.status = message
    persist_dataframe(record_history=False)


def undo_changes() -> None:
    if can_undo():
        target = st.session_state.history_index - 1
        apply_history_snapshot(target, "이전 상태로 되돌렸습니다.")


def redo_changes() -> None:
    if can_redo():
        target = st.session_state.history_index + 1
        apply_history_snapshot(target, "다음 상태로 이동했습니다.")


def get_current_file_path() -> Path:
    filename = st.session_state.get("current_file", "sample-list.csv") or "sample-list.csv"
    filename = filename.strip() or "sample-list.csv"
    return BASE_DIR / filename


def persist_dataframe(record_history: bool = True) -> None:
    path = get_current_file_path()
    suffix = path.suffix.lower()
    try:
        if suffix in {".xlsx", ".xls", ".xlsm"}:
            st.session_state.df.to_excel(path, index=False)
        else:
            st.session_state.df.to_csv(path, index=False)
        remember_last_file(path)
        ensure_row_selection_length()
        if record_history:
            record_history_snapshot()
    except Exception as exc:
        st.warning(f"{path.name} 자동 저장 실패: {exc}")


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
    return sanitize_dataframe(df)


def load_local_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)
    return sanitize_dataframe(df)


def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=list(DEFAULT_ROW.keys()))
    df = df.loc[:, ~df.columns.astype(str).str.contains(r"^Unnamed")]
    df = df.reset_index(drop=True)
    df = df.replace({pd.NA: "", None: ""})
    df = df.fillna("")
    df = df.astype(str).applymap(
        lambda v: "" if str(v).strip().lower() in {"none", "null", "nan", "-"} else str(v)
    )
    df = normalize_special_columns(df)
    df = normalize_select_columns(df)
    df = ensure_location_column(df)
    df[LOCATION_COLUMN] = df[LOCATION_COLUMN].apply(normalize_location_value)
    return df


def ensure_location_column(df: pd.DataFrame) -> pd.DataFrame:
    if LOCATION_COLUMN in df.columns:
        has_value = df[LOCATION_COLUMN].astype(str).str.strip().any()
        if has_value:
            return df
    for candidate in LOCATION_CANDIDATE_COLUMNS:
        if candidate == LOCATION_COLUMN:
            continue
        if candidate in df.columns:
            has_value = df[candidate].astype(str).str.strip().any()
            if has_value:
                df[LOCATION_COLUMN] = df[candidate]
                return df
    df[LOCATION_COLUMN] = "미지정"
    return df


def get_location_series(df: pd.DataFrame) -> pd.Series:
    if LOCATION_COLUMN in df.columns:
        series = df[LOCATION_COLUMN]
        if series.astype(str).str.strip().any():
            return series
    for candidate in LOCATION_CANDIDATE_COLUMNS:
        if candidate == LOCATION_COLUMN:
            continue
        if candidate in df.columns:
            series = df[candidate]
            if series.astype(str).str.strip().any():
                return series
    return pd.Series(["미지정"] * len(df), index=df.index)


def normalize_location_value(value: str | None) -> str:
    if value is None:
        return "미지정"
    text = str(value).strip()
    if not text:
        return "미지정"
    key = text.replace(" ", "").upper()
    if key in {"C", "C관", "C-GWAN", "CGWAN"}:
        return "C관"
    if key in {"S", "S관", "S-GWAN", "SGWAN"}:
        return "S관"
    if key in {"FRP", "FRP관"}:
        return "FRP"
    return text


def normalize_special_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "DIA" in df.columns:
        df["DIA"] = df["DIA"].apply(normalize_dia_value)
    return df


def normalize_select_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in SELECT_COLUMN_OPTIONS.keys():
        if column in df.columns:
            df[column] = df[column].apply(lambda v: normalize_cell_value(column, v))
    return df


FILTER_PRESETS = {
    "주간": lambda today: (today - timedelta(days=7), today),
    "월별": lambda today: (today - timedelta(days=30), today),
    "분기별": lambda today: (today - timedelta(days=90), today),
    "반기별": lambda today: (today - timedelta(days=182), today),
    "년도별": lambda today: (today - timedelta(days=365), today),
}


DATE_FILTER_COLUMNS = [
    "배송/예정일",
    "납기 요청일",
    "샘플 접수일",
]


def get_filter_column(df: pd.DataFrame) -> str | None:
    for column in DATE_FILTER_COLUMNS:
        if column in df.columns:
            return column
    return None


def prepare_dashboard_data(
    df: pd.DataFrame,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    if df.empty:
        return df
    filter_column = get_filter_column(df)
    if filter_column is None:
        filtered = df.copy()
    else:
        parsed = df[filter_column].apply(parse_date)
        df = df.copy()
        df["__parsed_date__"] = parsed
        filtered = df[
            df["__parsed_date__"].apply(
                lambda dt: dt is None or start_date <= dt <= end_date
            )
        ].copy()
    filtered = filtered.reset_index(drop=True)
    filtered = ensure_location_column(filtered)
    filtered[LOCATION_COLUMN] = filtered[LOCATION_COLUMN].apply(normalize_location_value)
    if not filtered.empty:
        stage_series = filtered.apply(
            lambda row: determine_stage(row, end_date), axis=1
        )
        filtered.loc[:, "__stage__"] = stage_series.values
    else:
        filtered["__stage__"] = []
    if "__parsed_date__" in filtered.columns:
        filtered = filtered.drop(columns=["__parsed_date__"])
    return filtered


def render_period_selector(
    today: datetime, key_prefix: str
) -> tuple[str, datetime, datetime]:
    period_options = list(FILTER_PRESETS.keys())
    period_choice = st.radio(
        "조회 범위",
        period_options,
        horizontal=True,
        index=1,
        label_visibility="collapsed",
        key=f"{key_prefix}_period",
    )
    preset_start, preset_end = FILTER_PRESETS[period_choice](today)
    if period_choice in {"월별", "분기별", "반기별", "년도별"}:
        expander_col, _ = st.columns([1.5, 2])
        with expander_col.expander("기간 선택", expanded=False):
            col_a, col_b = st.columns(2)
            preset_start = col_a.date_input(
                "시작일",
                value=preset_start.date(),
                max_value=today.date(),
                key=f"{key_prefix}_start",
            )
            preset_end = col_b.date_input(
                "종료일",
                value=preset_end.date(),
                max_value=today.date(),
                key=f"{key_prefix}_end",
            )
            if preset_start > preset_end:
                st.warning("시작일이 종료일보다 클 수 없습니다.")
                st.stop()
            preset_start = datetime.combine(preset_start, datetime.min.time())
            preset_end = datetime.combine(preset_end, datetime.max.time())
    return period_choice, preset_start, preset_end


def normalize_query_value(value, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, list):
        return value[0] if value else default
    return str(value)


def set_query_params(**kwargs: str) -> None:
    st.query_params = {k: v for k, v in kwargs.items() if v is not None}


def build_location_stage_summary(df: pd.DataFrame) -> OrderedDict[str, dict[str, int]]:
    summary = OrderedDict((loc, {stage: 0 for stage in STAGE_ORDER}) for loc in LOCATION_DISPLAY_ORDER)
    if df.empty:
        return summary
    locations = get_location_series(df).apply(normalize_location_value)
    grouped = df.groupby(locations)
    for location, group in grouped:
        if location in summary:
            counts = group["__stage__"].value_counts().reindex(STAGE_ORDER, fill_value=0)
            summary[location] = counts.to_dict()
    return summary


def build_location_bar_chart(stage_summary: OrderedDict[str, dict[str, int]]) -> go.Figure:
    locations = list(stage_summary.keys())
    fig = go.Figure()
    for stage in STAGE_ORDER:
        values = [stage_summary[loc].get(stage, 0) for loc in locations]
        fig.add_trace(
            go.Bar(
                y=locations,
                x=values,
                name=stage,
                orientation="h",
                marker_color=STAGE_COLORS.get(stage, "#d1d5db"),
                hovertemplate=f"{stage}: %{{x}}건<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        height=max(140, 70 * len(locations)),
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
    )
    fig.update_yaxes(title=None, automargin=True)
    fig.update_xaxes(visible=False)
    return fig


def render_location_card(stage_summary: OrderedDict[str, dict[str, int]]) -> str:
    rows_html: list[str] = []
    for loc, data in stage_summary.items():
        total = sum(data.values())
        segments: list[str] = []
        if total > 0:
            for stage in STAGE_ORDER:
                count = data.get(stage, 0)
                if not count:
                    continue
                percentage = (count / total) * 100
                segments.append(
                    f"<div class='factory-bar-segment' style='width:{percentage:.4f}%;background:{STAGE_COLORS.get(stage, '#d1d5db')}' title='{stage}: {count}건'></div>"
                )
        bar_inner = "".join(segments) if segments else "<div class='factory-bar-empty'>데이터 없음</div>"
        query = urlencode({"view": "factory", "factory": loc})
        safe_query = html.escape(query, quote=True)
        rows_html.append(
            f"<div class='factory-row'><div class='factory-name'>{loc}</div><div class='factory-row-bar'>{bar_inner}</div><a class='factory-detail-btn' href='?{safe_query}'>상세보기</a></div>"
        )
    card_html = (
        "<div class='chart-card factory-card'><div class='chart-card-title'>공장별 샘플 진행 현황</div>"
        + "".join(rows_html)
        + "</div>"
    )
    return card_html


def render_chart_card(
    fig: go.Figure,
    title: str | None = None,
    *,
    chart_width: int | None = None,
    chart_height: int | None = None,
    card_width: int = 560,
) -> None:
    width = chart_width or fig.layout.width or 420
    height = chart_height or fig.layout.height or 360
    fig.update_layout(width=width, height=height, margin=dict(t=20, b=20, l=10, r=10))
    html = fig.to_html(include_plotlyjs="cdn", full_html=False)
    title_html = (
        "<div style='font-weight:700;color:#1f2937;margin-bottom:0.4rem;'>"
        f"{title}</div>"
        if title
        else ""
    )
    style_block = f"""
    <style>
    html, body {{
        margin: 0;
        padding: 0;
    }}
    .inline-chart-card {{
        background:#fff;
        border-radius:1rem;
        border:1px solid #dfe4f2;
        padding:0.75rem 1rem 1rem;
        margin:0 0 1rem;
        width:{card_width}px;
        max-width:{card_width}px;
        box-sizing:border-box;
        box-shadow:none;
    }}
    .inline-chart-body {{
        display:flex;
        justify-content:center;
    }}
    </style>
    """
    card_html = (
        style_block
        + "<div class='inline-chart-card'>"
        + title_html
        + "<div class='inline-chart-body'>"
        + html
        + "</div></div>"
    )
    components.html(
        card_html,
        height=int(fig.layout.height or 400) + (60 if title else 40),
        scrolling=False,
    )


def render_sample_dashboard() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="display:flex; flex-direction:column; gap:0.4rem; margin-bottom:1.2rem;">
            <div style="font-size:2.2rem; font-weight:800; color:#1f2937;">샘플 진행 현황</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    today = datetime.now()
    st.caption(f"{today:%Y년 %m월 %d일 %H:%M 기준}")
    _, preset_start, preset_end = render_period_selector(today, "main")

    target_df = prepare_dashboard_data(
        st.session_state.df, preset_start, preset_end
    )
    period_text = f"{preset_start:%Y년 %m월 %d일} ~ {preset_end:%Y년 %m월 %d일} 데이터 기준"
    if target_df.empty:
        st.info("해당 기간에 등록된 샘플이 없습니다.")
        return

    stage_counts = (
        target_df["__stage__"]
        .value_counts()
        .reindex(STAGE_ORDER, fill_value=0)
    )

    summary_df = pd.DataFrame(
        {
            "stage": stage_counts.index,
            "count": stage_counts.values,
            "color": [STAGE_COLORS.get(stage, "#cccccc") for stage in stage_counts.index],
        }
    )
    summary_df["display_value"] = summary_df["count"].replace(0, 0.0001)

    left_col, right_col = st.columns([1.2, 1])
    with left_col:
        st.markdown("<div class='left-column-wrap'>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='left-caption'>{period_text}</div>",
            unsafe_allow_html=True,
        )
        fig = px.pie(
            summary_df,
            values="display_value",
            names="stage",
            color="stage",
            category_orders={"stage": STAGE_ORDER},
            color_discrete_map=STAGE_COLORS,
        )
        fig.update_layout(
            margin=dict(l=20, r=20, t=10, b=10),
            showlegend=False,
        )
        fig.update_traces(
            text=summary_df["count"],
            textinfo="text",
            hole=0.35,
            hovertemplate="%{label}: %{text}건",
        )
        render_chart_card(fig)
        legend_html = "".join(
            f"<span><span class='legend-dot' style='background:{STAGE_COLORS.get(stage, '#d1d5db')}'></span>{stage}</span>"
            for stage in STAGE_ORDER
        )
        location_summary = build_location_stage_summary(target_df)
        location_card_html = render_location_card(location_summary)
        st.markdown(
            f"<div class='left-stack'><div class='status-legend'>{legend_html}</div>{location_card_html}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    with right_col:
        st.markdown('<div class="status-list">', unsafe_allow_html=True)
        for stage in STAGE_ORDER:
            entries = target_df[target_df["__stage__"] == stage]
            color = STAGE_COLORS.get(stage, "#cccccc")
            if entries.empty:
                items_html = '<div class="status-empty">해당 항목이 없습니다.</div>'
            else:
                lines = []
                for _, row in entries.head(2).iterrows():
                    summary_text = " / ".join(
                        filter(
                            None,
                            [
                                str(row.get("국가", "")).strip(),
                                str(row.get("고객사", "")).strip(),
                                str(row.get("품명", "")).strip(),
                            ],
                        )
                    )
                    lines.append(f'<div class="status-item">{summary_text}</div>')
                if len(entries) > 2:
                    lines.append(f'<div class="status-item">…외 {len(entries) - 2}건</div>')
                items_html = '<div class="status-items">' + "".join(lines) + "</div>"

            st.markdown(
                f"""
                <div class="status-card" style="border-left-color:{color};">
                    <div class="status-info">
                        <div class="status-name">{stage}</div>
                        {items_html}
                    </div>
                    <div class="status-count">{len(entries)}건</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)


def render_factory_detail_page(factory_name: str) -> None:
    today = datetime.now()
    st.markdown(
        f"""
        <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:0.6rem;">
            <div>
                <div style="font-size:2rem;font-weight:800;color:#1f2937;">샘플 진행 현황 - {factory_name}</div>
                <div style="color:#6b7280;">{today:%Y년 %m월 %d일 %H:%M 기준}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, preset_start, preset_end = render_period_selector(today, f"factory_{factory_name}")
    st.caption(f"{preset_start:%Y년 %m월 %d일} ~ {preset_end:%Y년 %m월 %d일} 데이터 기준")

    target_df = prepare_dashboard_data(
        st.session_state.df, preset_start, preset_end
    )
    target_df = target_df[target_df[LOCATION_COLUMN] == factory_name]
    if target_df.empty:
        st.info(f"{factory_name}에 해당하는 샘플이 없습니다.")
        return

    stage_counts = (
        target_df["__stage__"].value_counts().reindex(STAGE_ORDER, fill_value=0)
    )

    fig = go.Figure()
    for stage in STAGE_ORDER:
        value = stage_counts[stage]
        if not value:
            continue
        fig.add_trace(
            go.Bar(
                y=[factory_name],
                x=[value],
                name=stage,
                orientation="h",
                marker_color=STAGE_COLORS.get(stage, "#d1d5db"),
                hovertemplate=f"{stage}: %{{x}}건<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack",
        height=140,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
    )
    fig.update_yaxes(visible=False)
    fig.update_xaxes(visible=False)
    render_chart_card(fig, chart_width=560, chart_height=200, card_width=560)

    legend_html = "".join(
        f"<span><span class='legend-dot' style='background:{STAGE_COLORS.get(stage, '#d1d5db')}'></span>{stage} {int(stage_counts[stage])}건</span>"
        for stage in STAGE_ORDER
    )
    st.markdown(
        f"<div class='status-legend'>{legend_html}</div>",
        unsafe_allow_html=True,
    )

    detail_df = target_df.drop(columns=["__stage__"])
    st.dataframe(
        detail_df,
        use_container_width=True,
        height=min(600, 200 + 35 * len(detail_df)),
    )


def render_limit_dashboard() -> None:
    st.title("한도 제작 현황")
    st.info("한도 제작 대시보드는 추후 구현 예정입니다.")


def snapshot_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy(deep=True)


def copy_from_snapshot(snapshot: pd.DataFrame) -> pd.DataFrame:
    return snapshot.copy(deep=True)


def build_column_config(df: pd.DataFrame) -> dict[str, st.column_config.Column]:
    config: dict[str, st.column_config.Column] = {}
    for column in df.columns:
        options = SELECT_COLUMN_OPTIONS.get(column)
        if options:
            config[column] = st.column_config.SelectboxColumn(
                column,
                options=options,
                default="",
            )
        else:
            config[column] = st.column_config.TextColumn(column)
    return config


def ensure_extension(filename: str, extension: str) -> str:
    filename = filename.strip() or "sample-list"
    if not filename.lower().endswith(extension):
        filename += extension
    return filename


def list_local_data_files() -> list[Path]:
    targets = list(BASE_DIR.glob("*.csv")) + list(BASE_DIR.glob("*.xlsx"))
    targets.sort(key=lambda p: p.name.lower())
    return targets


def add_column(label: str) -> None:
    label = label.strip()
    if not label:
        st.warning("열 이름을 입력해 주세요.")
        return
    if label in st.session_state.df.columns:
        st.warning("이미 존재하는 열입니다.")
        return
    st.session_state.df[label] = ""
    st.session_state.status = f"'{label}' 열을 추가했습니다."
    persist_dataframe()


def rename_column(old: str, new: str) -> None:
    new = new.strip()
    if not old or not new:
        st.warning("대상 열과 새 이름을 모두 입력하세요.")
        return
    if new in st.session_state.df.columns:
        st.warning("같은 이름의 열이 이미 있습니다.")
        return
    st.session_state.df = st.session_state.df.rename(columns={old: new})
    st.session_state.status = f"'{old}' → '{new}' 열 이름을 변경했습니다."
    persist_dataframe()


def delete_column(target: str) -> None:
    if not target:
        return
    st.session_state.df = st.session_state.df.drop(columns=[target])
    st.session_state.status = f"'{target}' 열을 삭제했습니다."
    persist_dataframe()


def add_row() -> None:
    if st.session_state.df.empty:
        st.session_state.df = pd.DataFrame(columns=list(DEFAULT_ROW.keys()))
    empty_row = {col: "" for col in st.session_state.df.columns}
    st.session_state.df = pd.concat(
        [st.session_state.df, pd.DataFrame([empty_row])],
        ignore_index=True,
    )
    st.session_state.status = "빈 행을 추가했습니다."
    persist_dataframe()


def delete_last_row() -> None:
    if st.session_state.df.empty:
        st.info("삭제할 행이 없습니다.")
        return
    st.session_state.df = st.session_state.df.iloc[:-1].reset_index(drop=True)
    st.session_state.status = "마지막 행을 삭제했습니다."
    persist_dataframe()


def get_selected_rows() -> list[int]:
    ensure_row_selection_length()
    return [
        idx
        for idx, flag in enumerate(st.session_state.row_selection)
        if flag and idx < len(st.session_state.df)
    ]


def delete_selected_rows() -> None:
    targets = get_selected_rows()
    if not targets:
        st.info("삭제할 행을 먼저 선택하세요.")
        return
    st.session_state.df = st.session_state.df.drop(index=targets).reset_index(drop=True)
    st.session_state.row_selection = [
        flag for idx, flag in enumerate(st.session_state.row_selection) if idx not in targets
    ]
    st.session_state.status = f"{len(targets)}개 행을 삭제했습니다."
    persist_dataframe()


def handle_table_edit() -> None:
    editor_state = st.session_state.get("data_editor")
    if not editor_state:
        return

    df = st.session_state.df.copy()
    row_selection = st.session_state.row_selection.copy()
    changed = False

    edited_rows = editor_state.get("edited_rows") or {}
    for idx_key, updates in edited_rows.items():
        try:
            idx = int(idx_key)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(df):
            continue
        for column, value in updates.items():
            if column == SELECTION_COLUMN:
                ensure_row_selection_length()
                while len(row_selection) <= idx:
                    row_selection.append(False)
                flag = bool(value)
                if row_selection[idx] != flag:
                    row_selection[idx] = flag
                    changed = True
                continue
            normalized = normalize_cell_value(column, value)
            if df.at[idx, column] != normalized:
                df.at[idx, column] = normalized
                changed = True

    added_rows = editor_state.get("added_rows") or []
    for row in added_rows:
        new_row = {col: "" for col in df.columns}
        for column, value in row.items():
            if column == SELECTION_COLUMN:
                continue
            if column in new_row:
                new_row[column] = normalize_cell_value(column, value)
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        row_selection.append(bool(row.get(SELECTION_COLUMN, False)))
        changed = True

    deleted_rows = editor_state.get("deleted_rows") or []
    if deleted_rows:
        for raw in sorted({int(r) for r in deleted_rows}, reverse=True):
            if 0 <= raw < len(df):
                df = df.drop(index=raw)
                if raw < len(row_selection):
                    row_selection.pop(raw)
                changed = True
        df = df.reset_index(drop=True)

    if changed:
        sanitized = sanitize_dataframe(df)
        st.session_state.df = sanitized
        ensure_len = len(sanitized)
        if len(row_selection) < ensure_len:
            row_selection.extend([False] * (ensure_len - len(row_selection)))
        st.session_state.row_selection = row_selection[:ensure_len]
        st.session_state.status = "테이블을 업데이트했습니다."
        persist_dataframe()
    else:
        ensure_row_selection_length()


def render_admin_page() -> None:
    st.title("샘플 리스트 관리자")
    st.caption("CSV/엑셀을 불러와 열과 행을 자유롭게 조정하고 다시 저장해 보세요.")

    if st.session_state.status:
        st.info(st.session_state.status)

    with st.container():
        st.subheader("파일 불러오기 / 저장")
        c1, c2 = st.columns([2, 1])

        with c1:
            uploaded = st.file_uploader(
                "CSV 또는 엑셀 파일을 선택하세요",
                type=["csv", "xlsx", "xls"],
                help="파일을 업로드하면 현재 테이블이 해당 내용으로 교체됩니다.",
            )
            if uploaded is not None:
                signature = f"{uploaded.name}:{uploaded.size}"
                if st.session_state.last_uploaded_sig != signature:
                    st.session_state.df = read_uploaded_file(uploaded)
                    st.session_state.current_file = uploaded.name
                    st.session_state.status = f"{uploaded.name} 불러오기 완료"
                    st.session_state.last_uploaded_sig = signature
                    reset_history()
                    st.rerun()

            local_files = list_local_data_files()
            if local_files:
                selected_name = st.selectbox(
                    "같은 폴더의 파일 불러오기",
                    ["선택하지 않음"] + [path.name for path in local_files],
                    index=0,
                )
                if selected_name != "선택하지 않음":
                    if st.button("선택 파일 불러오기", key="load_local"):
                        path = BASE_DIR / selected_name
                        st.session_state.df = load_local_file(path)
                        st.session_state.current_file = selected_name
                        st.session_state.status = f"{selected_name} 불러오기 완료"
                        st.session_state.last_uploaded_sig = None
                        remember_last_file(path)
                        reset_history()
                        st.rerun()
            else:
                st.caption("현재 폴더에 CSV/엑셀 파일이 없습니다.")

        with c2:
            file_name = st.text_input(
                "저장 파일 이름",
                value=st.session_state.current_file,
                help="확장자는 자동으로 붙습니다.",
            )
            save_col1, save_col2 = st.columns(2)
            with save_col1:
                if st.button("CSV로 저장", use_container_width=True):
                    target = BASE_DIR / ensure_extension(file_name, ".csv")
                    st.session_state.df.to_csv(target, index=False)
                    st.session_state.current_file = target.name
                    remember_last_file(target)
                    st.success(f"{target.name} 저장 완료")
            with save_col2:
                if st.button("엑셀로 저장", use_container_width=True):
                    target = BASE_DIR / ensure_extension(file_name, ".xlsx")
                    st.session_state.df.to_excel(target, index=False)
                    st.session_state.current_file = target.name
                    remember_last_file(target)
                    st.success(f"{target.name} 저장 완료")

            csv_bytes = build_csv_bytes(st.session_state.df)
            st.download_button(
                "CSV 다운로드",
                data=csv_bytes,
                file_name=ensure_extension(file_name, ".csv"),
                mime="text/csv",
                use_container_width=True,
            )
            excel_bytes = build_excel_bytes(st.session_state.df)
            st.download_button(
                "엑셀 다운로드",
                data=excel_bytes,
                file_name=ensure_extension(file_name, ".xlsx"),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.divider()

    st.subheader("열 관리")
    col_add, col_rename, col_delete = st.columns(3)

    with col_add:
        new_col = st.text_input("새 열 이름", key="new_col")
        if st.button("열 추가", use_container_width=True):
            add_column(new_col)
            st.rerun()

    with col_rename:
        columns = list(st.session_state.df.columns)
        selected_old = (
            st.selectbox("변경할 열", columns, key="rename_select") if columns else ""
        )
        new_label = st.text_input("새 이름", key="rename_value")
        if st.button("열 이름 변경", use_container_width=True, disabled=not columns):
            rename_column(selected_old, new_label)
            st.rerun()

    with col_delete:
        columns = list(st.session_state.df.columns)
        target = (
            st.selectbox("삭제할 열", columns, key="delete_select") if columns else ""
        )
        if st.button("열 삭제", use_container_width=True, disabled=not columns):
            delete_column(target)
            st.rerun()

    st.divider()

    row_controls = st.container()
    history_controls = st.container()

    st.divider()

    st.subheader("데이터 테이블")
    ensure_row_selection_length()
    display_df = st.session_state.df.copy()
    selection_series = pd.Series(st.session_state.row_selection, dtype=bool)
    display_df.insert(0, SELECTION_COLUMN, selection_series)

    column_config = {
        SELECTION_COLUMN: st.column_config.CheckboxColumn(
            SELECTION_LABEL,
            help="삭제할 행을 선택하세요.",
        ),
    }
    column_config.update(build_column_config(st.session_state.df))

    edited_df = st.data_editor(
        display_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="data_editor",
        on_change=handle_table_edit,
        column_config=column_config,
    )
    selection_flags = (
        edited_df.pop(SELECTION_COLUMN).astype(bool).tolist()
        if SELECTION_COLUMN in edited_df.columns
        else [False] * len(edited_df)
    )
    sanitized_editor = sanitize_dataframe(edited_df)
    st.session_state.row_selection = selection_flags[: len(sanitized_editor)]
    if not sanitized_editor.equals(st.session_state.df):
        st.session_state.df = sanitized_editor
        st.session_state.status = "테이블을 업데이트했습니다."
        persist_dataframe()
    else:
        ensure_row_selection_length()

    selected_rows = get_selected_rows()

    with row_controls:
        st.subheader("행 관리")
        row_col1, row_col2, row_col3 = st.columns(3)
        if row_col1.button("행 추가", use_container_width=True):
            add_row()
            st.rerun()
        if row_col2.button("마지막 행 삭제", use_container_width=True):
            delete_last_row()
            st.rerun()
        if row_col3.button(
            "선택 행 삭제",
            use_container_width=True,
            disabled=not selected_rows,
            help="데이터 테이블에서 체크한 행을 삭제합니다.",
        ):
            delete_selected_rows()
            st.rerun()

    with history_controls:
        st.subheader("변경 이력")
        hist_col1, hist_col2 = st.columns(2)
        if hist_col1.button("되돌리기", use_container_width=True, disabled=not can_undo()):
            undo_changes()
            st.rerun()
        if hist_col2.button("다시 실행", use_container_width=True, disabled=not can_redo()):
            redo_changes()
            st.rerun()


def build_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def build_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.read()


def main() -> None:
    init_state()
    bootstrap_from_last_file()
    ensure_history_initialized()
    inject_app_styles()
    st.markdown(
        """
        <style>
        .sidebar .sidebar-content {
            background: linear-gradient(180deg, #eef2ff, #f9fafb);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    params = st.query_params
    view_param = normalize_query_value(params.get("view"), "sample")
    factory_param = normalize_query_value(params.get("factory"), "")

    page_options = ("샘플 진행", "한도 제작", "관리 페이지")
    page_index = {"sample": 0, "factory": 0, "limit": 1, "admin": 2}.get(view_param, 0)
    page = st.sidebar.radio("페이지", page_options, index=page_index)

    if page == "샘플 진행":
        factory_options = ("전체",) + tuple(LOCATION_DISPLAY_ORDER)
        if view_param == "factory" and factory_param in LOCATION_DISPLAY_ORDER:
            factory_index = factory_options.index(factory_param)
        else:
            factory_index = 0
        selected_factory = st.sidebar.radio(
            "샘플 진행",
            factory_options,
            index=factory_index,
        )
        if selected_factory == "전체":
            set_query_params(view="sample")
            render_sample_dashboard()
        else:
            set_query_params(view="factory", factory=selected_factory)
            render_factory_detail_page(selected_factory)
    elif page == "한도 제작":
        set_query_params(view="limit")
        render_limit_dashboard()
    else:
        set_query_params(view="admin")
        render_admin_page()


if __name__ == "__main__":
    main()
