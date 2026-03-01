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
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
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
SCROLL_TO_TABLE_FLAG = "__scroll_to_data_table__"
LOCATION_COLUMN = "샘플제작 공장위치"
LOCATION_CANDIDATE_COLUMNS = [
    LOCATION_COLUMN,
    "샘플 제작공장위치",
    "샘플제작공장위치",
]
LOCATION_DISPLAY_ORDER = ["C관", "S관", "FRP"]
FACTORY_QUERY_CODE_TO_NAME = {
    "c": "C관",
    "s": "S관",
    "frp": "FRP",
}
FACTORY_NAME_TO_QUERY_CODE = {
    value: key for key, value in FACTORY_QUERY_CODE_TO_NAME.items()
}
LENS_CONFIRM_COLUMN = "렌즈 컨펌일"
LIMIT_CONFIRM_COLUMN = "한도 컨펌일"
LIMIT_BUILD_COLUMN = "한도 제작"
LIMIT_READY_TOKENS = {"MIN", "MAX", "MIN+MAX"}
DELAY_DATE_COLUMN = "납기 지연(발송일 변경)"

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


def parse_round_value(value) -> int:
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        try:
            return int(digits)
        except ValueError:
            pass
    try:
        return int(float(text))
    except ValueError:
        return 0


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
    "샘플 구분": ["", "1D", "M"],
    "함수율": ["", "38%", "43%", "45%", "55%"],
    "DIA": ["", "14.2", "14.5", "14.2\n14.5"],
    "착용기간": ["", "1D", "M"],
    "잉크 구분": ["", "액상", "파우더", "액상+파우더"],
    "제작 현황": ["", "대기", "진행중", "완료", "Drop"],
    "샘플제작 공장위치": ["", "C관", "S관", "FRP", "미지정"],
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
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null", "-", "nat"}:
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
    delay_date = parse_date(row.get(DELAY_DATE_COLUMN))
    if delay_date is not None:
        return "납기지연"
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


def inject_scroll_persistence() -> None:
    components.html(
        """
        <script>
        (() => {
          let hostWin = null;
          let hostDoc = null;
          try {
            hostWin = window.parent;
            hostDoc = hostWin.document;
          } catch (err) {
            return;
          }
          const NS = "sample-manager-scroll-v1";
          const WIN_Y_KEY = NS + ":winY";
          const WIN_X_KEY = NS + ":winX";
          const TABLE_TOP_KEY = NS + ":tableTop";
          const TABLE_LEFT_KEY = NS + ":tableLeft";

          const saveWindowScroll = () => {
            hostWin.sessionStorage.setItem(WIN_Y_KEY, String(hostWin.scrollY || 0));
            hostWin.sessionStorage.setItem(WIN_X_KEY, String(hostWin.scrollX || 0));
          };

          const findTableRoots = () =>
            Array.from(
              hostDoc.querySelectorAll(
                '[data-testid="stDataFrame"], [data-testid="stDataEditor"]'
              )
            );

          const findScrollCandidates = () => {
            const roots = findTableRoots();
            if (!roots.length) {
              return [];
            }

            const all = [];
            for (const root of roots) {
              all.push(root);
              all.push(...Array.from(root.querySelectorAll("div")));
            }

            const unique = Array.from(new Set(all));
            return unique.filter((el) => {
              const scrollY = el.scrollHeight - el.clientHeight;
              const scrollX = el.scrollWidth - el.clientWidth;
              if (scrollY <= 8 && scrollX <= 8) {
                return false;
              }
              if (el.clientHeight < 40 || el.clientWidth < 80) {
                return false;
              }
              return true;
            });
          };

          const pickPrimaryScroller = (candidates) => {
            if (!candidates.length) {
              return null;
            }
            const ranked = [...candidates].sort((a, b) => {
              const aScore =
                (a.scrollHeight - a.clientHeight) +
                (a.scrollWidth - a.clientWidth);
              const bScore =
                (b.scrollHeight - b.clientHeight) +
                (b.scrollWidth - b.clientWidth);
              return bScore - aScore;
            });
            return ranked[0];
          };

          const saveTableScrollFrom = (scroller) => {
            if (!scroller) {
              return;
            }
            hostWin.sessionStorage.setItem(
              TABLE_TOP_KEY,
              String(scroller.scrollTop || 0)
            );
            hostWin.sessionStorage.setItem(
              TABLE_LEFT_KEY,
              String(scroller.scrollLeft || 0)
            );
          };

          const bindTableScrollSaver = () => {
            const candidates = findScrollCandidates();
            if (!candidates.length) {
              return false;
            }

            for (const scroller of candidates) {
              if (scroller.dataset.scrollBound) {
                continue;
              }
              scroller.addEventListener(
                "scroll",
                () => saveTableScrollFrom(scroller),
                { passive: true }
              );
              scroller.dataset.scrollBound = "1";
            }
            return true;
          };

          const restoreWindowScroll = () => {
            const y = Number(hostWin.sessionStorage.getItem(WIN_Y_KEY) || "0");
            const x = Number(hostWin.sessionStorage.getItem(WIN_X_KEY) || "0");
            if (!Number.isNaN(y) || !Number.isNaN(x)) {
              hostWin.scrollTo(Number.isNaN(x) ? 0 : x, Number.isNaN(y) ? 0 : y);
            }
          };

          const restoreTableScroll = () => {
            const candidates = findScrollCandidates();
            const scroller = pickPrimaryScroller(candidates);
            if (!scroller) {
              return false;
            }
            const top = Number(hostWin.sessionStorage.getItem(TABLE_TOP_KEY) || "0");
            const left = Number(hostWin.sessionStorage.getItem(TABLE_LEFT_KEY) || "0");
            if (!Number.isNaN(top)) {
              scroller.scrollTop = top;
            }
            if (!Number.isNaN(left)) {
              scroller.scrollLeft = left;
            }
            return true;
          };

          const saveAllScrolls = () => {
            saveWindowScroll();
            const scroller = pickPrimaryScroller(findScrollCandidates());
            saveTableScrollFrom(scroller);
          };

          if (!hostWin.__sampleManagerScrollBound) {
            hostWin.addEventListener("scroll", saveWindowScroll, { passive: true });
            hostWin.addEventListener("beforeunload", saveAllScrolls);
            hostDoc.addEventListener("pointerdown", saveAllScrolls, true);
            hostDoc.addEventListener("keydown", saveAllScrolls, true);
            hostWin.__sampleManagerScrollBound = true;
          }

          let tries = 0;
          const timer = hostWin.setInterval(() => {
            tries += 1;
            restoreWindowScroll();
            const bound = bindTableScrollSaver();
            const restored = restoreTableScroll();
            if ((bound && restored) || tries > 50) {
              hostWin.clearInterval(timer);
            }
          }, 120);
        })();
        </script>
        """,
        height=0,
    )


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


def normalize_limit_token(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "-"}:
        return ""
    simplified = text.upper().replace(" ", "")
    simplified = simplified.replace("/", "+")
    if simplified in {"MINMAX", "MAXMIN"}:
        simplified = "MIN+MAX"
    if simplified in LIMIT_READY_TOKENS:
        return simplified
    if "MIN" in simplified and "MAX" in simplified:
        return "MIN+MAX"
    if "MIN" in simplified:
        return "MIN"
    if "MAX" in simplified:
        return "MAX"
    return text


def analyze_limit_entry(value: str | None) -> tuple[bool, str, str]:
    normalized = normalize_limit_token(value)
    has_min = "MIN" in normalized
    has_max = "MAX" in normalized
    ready = bool(normalized) and (has_min or has_max)
    if has_min and has_max:
        display = "MIN + MAX"
    elif has_min:
        display = "MIN"
    elif has_max:
        display = "MAX"
    else:
        display = value.strip() if isinstance(value, str) else (str(value).strip() if value else "-")
    missing: list[str] = []
    if not has_min:
        missing.append("MIN")
    if not has_max:
        missing.append("MAX")
    missing_text = ", ".join(missing) + " 제작 필요" if missing else "완료"
    return ready, display, missing_text


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


FILTER_DATE_COLUMN = "샘플 접수일"
FILTER_DATE_CANDIDATES = [
    FILTER_DATE_COLUMN,
    "샘플 최초 접수일",
    "샘플 (수정)접수일",
]
PERIOD_LABEL_STYLE = """
<style>
.period-field-label {
    font-size: 0.78rem;
    color: #6b7280;
    margin-bottom: 0.05rem;
    line-height: 1;
}
</style>
"""


def get_filter_date_series(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series([], index=df.index)
    fallback: pd.Series | None = None
    for column in FILTER_DATE_CANDIDATES:
        if column not in df.columns:
            continue
        series = df[column].apply(parse_date)
        if fallback is None:
            fallback = series
        if series.notna().any():
            return series
    if fallback is not None:
        return fallback
    return pd.Series([None] * len(df), index=df.index)


def prepare_dashboard_data(
    df: pd.DataFrame,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    if df.empty:
        return df
    working = df.copy()
    working = ensure_location_column(working)
    working[LOCATION_COLUMN] = working[LOCATION_COLUMN].apply(normalize_location_value)
    if working.empty:
        working["__stage__"] = []
        return working

    stage_series = working.apply(lambda row: determine_stage(row, end_date), axis=1)
    working.loc[:, "__stage__"] = stage_series.values

    parsed_dates = get_filter_date_series(working)
    working.loc[:, "__filter_date__"] = parsed_dates

    date_mask = working["__filter_date__"].apply(
        lambda dt: dt is None or start_date <= dt <= end_date
    )
    target = working[date_mask].copy()
    target = target.drop(columns=["__filter_date__"])
    target = target.reset_index(drop=True)
    return target


def prepare_limit_dashboard_data(
    df: pd.DataFrame,
    start_date: datetime,
    end_date: datetime,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    if df.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty, empty
    working = df.copy()
    if LIMIT_BUILD_COLUMN not in working.columns:
        working[LIMIT_BUILD_COLUMN] = ""
    working = ensure_location_column(working)
    working[LOCATION_COLUMN] = working[LOCATION_COLUMN].apply(normalize_location_value)

    sample_dates = get_filter_date_series(working)
    working.loc[:, "__sample_date__"] = sample_dates

    if "차수" in working.columns:
        rounds = working["차수"].apply(parse_round_value)
    else:
        rounds = pd.Series([0] * len(working))
    working.loc[:, "__round__"] = rounds

    eligible_mask = working["__round__"] >= 3
    date_mask = working["__sample_date__"].apply(
        lambda dt: dt is None or start_date <= dt <= end_date
    )
    table = working[date_mask].copy()
    if table.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty, empty

    analysis = pd.DataFrame(
        table[LIMIT_BUILD_COLUMN].apply(analyze_limit_entry).tolist(),
        columns=["__limit_ready__", "__limit_display__", "__limit_missing__"],
        index=table.index,
    )
    table = pd.concat([table, analysis], axis=1)

    if LENS_CONFIRM_COLUMN in table.columns:
        lens_dates = table[LENS_CONFIRM_COLUMN].apply(parse_date)
    else:
        lens_dates = pd.Series([None] * len(table), index=table.index)
    table.loc[:, "__lens_date__"] = lens_dates
    table.loc[:, "__lens_confirmed__"] = lens_dates.notna()

    if LIMIT_CONFIRM_COLUMN in table.columns:
        limit_confirm_dates = table[LIMIT_CONFIRM_COLUMN].apply(parse_date)
    else:
        limit_confirm_dates = pd.Series([None] * len(table), index=table.index)
    table.loc[:, "__limit_confirm_date__"] = limit_confirm_dates

    table = table.sort_values(
        by=["__lens_confirmed__", "__sample_date__"],
        ascending=[False, False],
    )
    ready_all = table[table["__limit_ready__"]].copy()
    confirmed_all = ready_all[ready_all["__lens_confirmed__"]].copy()
    pending_all = table[~table["__limit_ready__"]].copy()

    eligible_table = table[eligible_mask.loc[table.index]].copy()
    ready_eligible = ready_all.loc[ready_all.index.intersection(eligible_table.index)]
    confirmed_eligible = confirmed_all.loc[
        confirmed_all.index.intersection(eligible_table.index)
    ]
    pending_eligible = pending_all.loc[
        pending_all.index.intersection(eligible_table.index)
    ]
    return (
        confirmed_eligible,
        ready_eligible,
        pending_eligible,
        confirmed_all,
        ready_all,
        pending_all,
    )


def build_limit_view_table(
    df: pd.DataFrame,
    *,
    date_column: str = "__lens_date__",
    date_label: str = "렌즈 컨펌일",
) -> pd.DataFrame:
    if df.empty:
        return df
    base_index = df.index

    def pick(column: str) -> pd.Series:
        return df.get(column, pd.Series([""] * len(df), index=base_index))

    raw_dates = df.get(date_column, pd.Series([""] * len(df), index=base_index))
    formatted_dates = []
    for value in raw_dates:
        if value is None or pd.isna(value):
            formatted_dates.append("-")
        elif isinstance(value, pd.Timestamp):
            if pd.isna(value):
                formatted_dates.append("-")
            else:
                formatted_dates.append(value.strftime("%Y-%m-%d"))
        elif isinstance(value, datetime):
            formatted_dates.append(value.strftime("%Y-%m-%d"))
        elif str(value).strip() == "":
            formatted_dates.append("-")
        else:
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed):
                formatted_dates.append("-")
            else:
                formatted_dates.append(parsed.strftime("%Y-%m-%d"))
    formatted_dates = pd.Series(formatted_dates, index=base_index)

    view = pd.DataFrame(
        {
            date_label: formatted_dates,
            "국가": pick("국가"),
            "고객사": pick("고객사"),
            "품명": pick("품명"),
            "샘플 구분": pick("샘플 구분"),
            "차수": pick("차수"),
            "한도 제작": df["__limit_display__"],
            "필요 작업": df["__limit_missing__"],
            "비고": pick("비고"),
        }
    )
    return view.fillna("")


def list_available_years(today: datetime) -> list[int]:
    years = {today.year}
    df = st.session_state.get("df")
    if isinstance(df, pd.DataFrame) and not df.empty:
        parsed = get_filter_date_series(df)
        for dt in parsed:
            if isinstance(dt, datetime):
                years.add(dt.year)
    return sorted(years, reverse=True)


def advance_month(year: int, month: int, months: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + months
    new_year = total // 12
    new_month = total % 12 + 1
    return new_year, new_month


def build_period_bounds(year: int, start_month: int, months: int) -> tuple[datetime, datetime]:
    start = datetime(year, start_month, 1)
    end_year, end_month = advance_month(year, start_month, months)
    next_period_start = datetime(end_year, end_month, 1)
    end = next_period_start - timedelta(seconds=1)
    return start, end


def render_month_selector(
    today: datetime,
    key_prefix: str,
    year_col,
    month_col,
) -> tuple[datetime, datetime]:
    ensure_period_label_style()
    render_period_field_label(year_col, "년도")
    years = list_available_years(today)
    year_index = years.index(today.year) if today.year in years else 0
    selected_year = year_col.selectbox(
        "년도",
        years,
        index=year_index,
        key=f"{key_prefix}_month_year",
        label_visibility="collapsed",
    )
    render_period_field_label(month_col, "월")
    month_options = list(range(1, 13))
    month_index = max(0, min(len(month_options) - 1, today.month - 1))
    selected_month = month_col.selectbox(
        "월",
        month_options,
        index=month_index,
        format_func=lambda value: f"{value}월",
        key=f"{key_prefix}_month_value",
        label_visibility="collapsed",
    )
    return build_period_bounds(selected_year, selected_month, 1)


def render_quarter_selector(
    today: datetime,
    key_prefix: str,
    year_col,
    quarter_col,
) -> tuple[datetime, datetime]:
    ensure_period_label_style()
    render_period_field_label(year_col, "년도")
    years = list_available_years(today)
    year_index = years.index(today.year) if today.year in years else 0
    selected_year = year_col.selectbox(
        "년도",
        years,
        index=year_index,
        key=f"{key_prefix}_quarter_year",
        label_visibility="collapsed",
    )
    render_period_field_label(quarter_col, "분기")
    quarter_options = [1, 2, 3, 4]
    current_quarter = ((today.month - 1) // 3) + 1
    quarter_index = quarter_options.index(current_quarter)
    selected_quarter = quarter_col.selectbox(
        "분기",
        quarter_options,
        index=quarter_index,
        format_func=lambda value: f"{value}분기",
        key=f"{key_prefix}_quarter_value",
        label_visibility="collapsed",
    )
    start_month = (selected_quarter - 1) * 3 + 1
    return build_period_bounds(selected_year, start_month, 3)


def render_half_selector(
    today: datetime,
    key_prefix: str,
    year_col,
    half_col,
) -> tuple[datetime, datetime]:
    ensure_period_label_style()
    render_period_field_label(year_col, "년도")
    years = list_available_years(today)
    year_index = years.index(today.year) if today.year in years else 0
    selected_year = year_col.selectbox(
        "년도",
        years,
        index=year_index,
        key=f"{key_prefix}_half_year",
        label_visibility="collapsed",
    )
    render_period_field_label(half_col, "반기")
    half_options = [1, 2]
    current_half = 1 if today.month <= 6 else 2
    half_index = current_half - 1
    selected_half = half_col.selectbox(
        "반기",
        half_options,
        index=half_index,
        format_func=lambda value: "상반기" if value == 1 else "하반기",
        key=f"{key_prefix}_half_value",
        label_visibility="collapsed",
    )
    start_month = 1 if selected_half == 1 else 7
    return build_period_bounds(selected_year, start_month, 6)


def render_year_selector(
    today: datetime,
    key_prefix: str,
    year_col,
) -> tuple[datetime, datetime]:
    ensure_period_label_style()
    render_period_field_label(year_col, "년도")
    years = list_available_years(today)
    year_index = years.index(today.year) if today.year in years else 0
    selected_year = year_col.selectbox(
        "년도",
        years,
        index=year_index,
        key=f"{key_prefix}_year_value",
        label_visibility="collapsed",
    )
    return build_period_bounds(selected_year, 1, 12)


def render_period_field_label(target, text: str) -> None:
    target.markdown(
        f"<div class='period-field-label'>{text}</div>",
        unsafe_allow_html=True,
    )


def ensure_period_label_style() -> None:
    if not st.session_state.get("__period_label_style", False):
        st.markdown(PERIOD_LABEL_STYLE, unsafe_allow_html=True)
        st.session_state["__period_label_style"] = True


def sync_manual_period_inputs(
    key_prefix: str,
    start_dt: datetime,
    end_dt: datetime,
    start_col,
    end_col,
) -> tuple[datetime, datetime]:
    ensure_period_label_style()
    start_key = f"{key_prefix}_start"
    end_key = f"{key_prefix}_end"
    signature_key = f"{key_prefix}_auto_sig"
    start_date = start_dt.date()
    end_date = end_dt.date()
    signature = f"{start_date.isoformat()}|{end_date.isoformat()}"

    if start_key not in st.session_state:
        st.session_state[start_key] = start_date
    if end_key not in st.session_state:
        st.session_state[end_key] = end_date

    if st.session_state.get(signature_key) != signature:
        st.session_state[start_key] = start_date
        st.session_state[end_key] = end_date
        st.session_state[signature_key] = signature

    render_period_field_label(start_col, "시작일")
    manual_start = start_col.date_input(
        "시작일",
        key=start_key,
        label_visibility="collapsed",
    )
    render_period_field_label(end_col, "종료일")
    manual_end = end_col.date_input(
        "종료일",
        key=end_key,
        label_visibility="collapsed",
    )
    if manual_start > manual_end:
        st.warning("시작일이 종료일보다 클 수 없습니다.")
        st.stop()
    manual_start_dt = datetime.combine(manual_start, datetime.min.time())
    manual_end_dt = datetime.combine(manual_end, datetime.max.time())
    return manual_start_dt, manual_end_dt


def render_period_selector(
    today: datetime, key_prefix: str
) -> tuple[str, datetime, datetime]:
    period_options = list(FILTER_PRESETS.keys())
    default_period = "분기별"
    default_period_index = (
        period_options.index(default_period) if default_period in period_options else 0
    )
    period_choice = st.radio(
        "조회 범위",
        period_options,
        horizontal=True,
        index=default_period_index,
        label_visibility="collapsed",
        key=f"{key_prefix}_period",
    )
    preset_start, preset_end = FILTER_PRESETS[period_choice](today)
    ranged_periods = {"월별", "분기별", "반기별", "년도별"}
    if period_choice in ranged_periods:
        expander_col, _ = st.columns([1.5, 2])
        with expander_col.expander("기간 선택", expanded=False):
            if period_choice == "년도별":
                col_year, col_start, col_end = st.columns([1, 1.3, 1.3])
                preset_start, preset_end = render_year_selector(
                    today, key_prefix, col_year
                )
            else:
                col_year, col_period, col_start, col_end = st.columns([1, 1, 1.3, 1.3])
                if period_choice == "월별":
                    preset_start, preset_end = render_month_selector(
                        today, key_prefix, col_year, col_period
                    )
                elif period_choice == "분기별":
                    preset_start, preset_end = render_quarter_selector(
                        today, key_prefix, col_year, col_period
                    )
                else:
                    preset_start, preset_end = render_half_selector(
                        today, key_prefix, col_year, col_period
                    )

            preset_start, preset_end = sync_manual_period_inputs(
                key_prefix,
                preset_start,
                preset_end,
                col_start,
                col_end,
            )
    return period_choice, preset_start, preset_end


def normalize_query_value(value, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, list):
        return value[0] if value else default
    return str(value)


def set_query_params(**kwargs: str) -> None:
    target = {k: str(v) for k, v in kwargs.items() if v is not None}
    current = {
        key: normalize_query_value(st.query_params.get(key), "")
        for key in st.query_params.keys()
    }
    if current != target:
        st.query_params = target


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
                if percentage >= 22:
                    label_text = f"{stage} {count}건"
                elif percentage >= 12:
                    label_text = f"{count}건"
                else:
                    label_text = ""
                label_html = (
                    f"<span class='factory-segment-label'>{html.escape(label_text)}</span>"
                    if label_text
                    else ""
                )
                segments.append(
                    f"<div class='factory-bar-segment' style='width:{percentage:.4f}%;background:{STAGE_COLORS.get(stage, '#d1d5db')}' title='{stage}: {count}건'>{label_html}</div>"
                )
            bar_inner = "".join(segments)
        else:
            bar_inner = "<div class='factory-bar-empty'>데이터 없음</div>"
        rows_html.append(
            "<div class='factory-row'>"
            f"<div class='factory-name'>{loc}</div>"
            f"<div class='factory-row-main'><div class='factory-row-bar'>{bar_inner}</div></div>"
            "</div>"
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
    base_size = 12
    if fig.layout.font and fig.layout.font.size:
        try:
            base_size = int(fig.layout.font.size)
        except (TypeError, ValueError):
            base_size = 12
    target_size = max(12, base_size + 1)

    fig.update_layout(
        font=dict(
            size=target_size,
            color="#1f2937",
            family="Pretendard Variable, Noto Sans KR, Segoe UI, sans-serif",
        )
    )
    fig.update_xaxes(
        tickfont=dict(size=target_size, color="#1f2937"),
        title_font=dict(size=target_size + 1, color="#1f2937"),
    )
    fig.update_yaxes(
        tickfont=dict(size=target_size, color="#1f2937"),
        title_font=dict(size=target_size + 1, color="#1f2937"),
    )
    fig.update_annotations(font=dict(size=target_size + 1, color="#1f2937"))

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
        width=card_width,
    )


def pick_first_valid_date(row: pd.Series, columns: list[str]) -> datetime | None:
    for column in columns:
        if column not in row:
            continue
        dt = parse_date(row.get(column))
        if dt is not None:
            return dt
    return None


def build_duration_entries(df: pd.DataFrame) -> list[dict]:
    design_to_ship: list[dict] = []
    for _, row in df.iterrows():
        customer = str(row.get("고객사") or "").strip()
        product = str(row.get("품명") or "").strip()
        country = str(row.get("국가") or "").strip()
        label_parts = [country, customer]
        if product:
            label_parts.append(product)
        label = " / ".join(part for part in label_parts if part) or "이름 없음"

        start_design = pick_first_valid_date(row, ["시안 컨펌일"])
        shipment_candidates = [
            pick_first_valid_date(row, ["발송 예정일"]),
            pick_first_valid_date(row, [DELAY_DATE_COLUMN]),
        ]
        shipment_dates = [dt for dt in shipment_candidates if dt is not None]
        end_ship = max(shipment_dates) if shipment_dates else None
        if start_design and end_ship and end_ship >= start_design:
            design_to_ship.append(
                {
                    "label": label,
                    "start": start_design,
                    "end": end_ship,
                    "days": max((end_ship - start_design).days, 0),
                }
            )
    return design_to_ship


def render_duration_trend_chart(
    shipment_entries: list[dict],
    *,
    width: int = 760,
    card_width: int | None = None,
) -> None:
    if not shipment_entries:
        st.info("소요일 정보를 계산할 데이터가 없습니다.")
        return

    fig = go.Figure()

    df = pd.DataFrame(shipment_entries)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df = df.sort_values("start")
    fig.add_trace(
        go.Scatter(
            x=df["start"],
            y=df["days"],
            mode="lines+markers+text",
            text=[f"<b>{int(day)}일</b>" for day in df["days"]],
            textposition="top center",
            textfont=dict(size=13),
            line=dict(color="#e36c5c", width=3),
            marker=dict(size=8, color="#e36c5c"),
            hovertemplate=(
                "%{text}<br>"
                "시안 컨펌: %{x|%Y-%m-%d}<br>"
                "발송: %{customdata}<extra></extra>"
            ),
            customdata=df["end"].dt.strftime("%Y-%m-%d"),
            name="시안 컨펌→발송",
        )
    )

    fig.update_layout(
        height=320,
        margin=dict(l=70, r=40, t=30, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title=dict(text="소요일 (일)", standoff=25),
        xaxis_title=dict(text="일정", standoff=30),
        yaxis=dict(
            gridcolor="#e5e7eb",
            tickfont=dict(size=10),
            ticklabelposition="outside",
            automargin=True,
        ),
        xaxis=dict(
            showgrid=True,
            gridcolor="#f1f5f9",
            tickformat="%b %Y",
            tickfont=dict(size=10),
            tickangle=-20,
            ticklabelposition="outside",
            automargin=True,
        ),
    )

    render_chart_card(
        fig,
        title="샘플 제작 소요일 추이",
        chart_width=width,
        chart_height=360,
        card_width=card_width or width,
    )


def render_sample_dashboard() -> None:
    st.markdown(
        """
        <div class="page-hero">
            <div class="page-hero-title">샘플 종합 진도 현황</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    today = datetime.now()
    st.markdown(
        f"<p class='page-caption'>{today:%Y년 %m월 %d일 %H:%M 기준}</p>",
        unsafe_allow_html=True,
    )
    _, preset_start, preset_end = render_period_selector(today, "main")

    target_df = prepare_dashboard_data(
        st.session_state.df, preset_start, preset_end
    )
    stage_idx_raw = normalize_query_value(st.query_params.get("stage_idx"), "")
    selected_stage_idx: int | None = None
    if str(stage_idx_raw).strip():
        try:
            candidate_idx = int(str(stage_idx_raw).strip())
            if 0 <= candidate_idx < len(STAGE_ORDER):
                selected_stage_idx = candidate_idx
        except ValueError:
            selected_stage_idx = None
    selected_stage = STAGE_ORDER[selected_stage_idx] if selected_stage_idx is not None else ""

    period_text = (
        f"{preset_start:%Y년 %m월 %d일} ~ {preset_end:%Y년 %m월 %d일} "
        "샘플 접수일 기준"
    )
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
    pie_df = summary_df[summary_df["count"] > 0].copy()
    total_count = int(stage_counts.sum())

    left_col, right_col = st.columns([1.2, 1])
    with left_col:
        left_panel = st.container(key="left_panel")
        with left_panel:
            st.markdown("<div class='left-column-wrap'>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='left-caption left-caption-strong'>{period_text}</div>",
                unsafe_allow_html=True,
            )
            fig = px.pie(
                pie_df,
                values="count",
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
                texttemplate="<b>%{label}</b><br><b>%{value}건</b>",
                textposition="inside",
                textfont=dict(size=14, color="#0f172a"),
                insidetextorientation="horizontal",
                hole=0.35,
                hovertemplate="%{label}: %{value}건<extra></extra>",
            )
            fig.add_annotation(
                text=f"<b>총 {total_count}건</b>",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=19, color="#1e293b"),
            )
            render_chart_card(
                fig,
                title="<span style='font-size:0.94rem;font-weight:600;color:#4b5563;'>샘플 종합 진도 현황</span>",
                chart_width=390,
                chart_height=310,
                card_width=500,
            )
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
            detail_cols = st.columns(len(LOCATION_DISPLAY_ORDER))
            for loc_idx, loc_name in enumerate(LOCATION_DISPLAY_ORDER):
                with detail_cols[loc_idx]:
                    if st.button(
                        f"{loc_name} 상세보기",
                        key=f"factory_detail_native_{loc_idx}",
                        use_container_width=True,
                    ):
                        nav_index = 1 + loc_idx
                        set_query_params(
                            view="factory",
                            factory=FACTORY_NAME_TO_QUERY_CODE.get(loc_name, loc_name),
                            nav=nav_index,
                        )
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    with right_col:
        status_panel = st.container(key="status_panel", gap="small")
        for stage_idx, stage in enumerate(STAGE_ORDER):
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

            selected_class = " status-card-selected" if selected_stage_idx == stage_idx else ""
            row_card_col, row_btn_col = status_panel.columns([4.8, 1.2], gap="small")
            with row_card_col:
                st.markdown(
                    f"""
                    <div class="status-card{selected_class}" style="border-left-color:{color};">
                        <div class="status-info">
                            <div class="status-name">{stage}</div>
                            {items_html}
                        </div>
                        <div class="status-count">{len(entries)}건</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with row_btn_col:
                if st.button(
                    "목록보기",
                    key=f"stage_popup_native_{stage_idx}",
                    use_container_width=True,
                ):
                    set_query_params(view="sample", stage_idx=stage_idx, nav=0)
                    st.rerun()
            if stage_idx < len(STAGE_ORDER) - 1:
                status_panel.markdown("<div class='status-row-gap'></div>", unsafe_allow_html=True)

    st.caption("오른쪽 목록보기 버튼을 클릭하면 해당 단계의 샘플 목록이 팝업으로 열립니다.")
    if selected_stage:
        selected_df = target_df[target_df["__stage__"] == selected_stage].copy()
        detail_df = selected_df.drop(columns=["__stage__"], errors="ignore")

        @st.dialog(f"{selected_stage} 샘플 목록 ({len(detail_df)}건)", width="large")
        def show_stage_samples_dialog() -> None:
            if detail_df.empty:
                st.info(f"{selected_stage} 상태에 해당하는 샘플이 없습니다.")
            else:
                st.dataframe(
                    detail_df,
                    use_container_width=True,
                    hide_index=True,
                    height=min(640, 220 + 34 * len(detail_df)),
                )
            if st.button("닫기", key=f"close_stage_dialog_{selected_stage}"):
                set_query_params(view="sample", stage_idx=None)
                st.rerun()

        show_stage_samples_dialog()


def render_factory_detail_page(factory_name: str) -> None:
    today = datetime.now()
    st.markdown(
        f"""
        <div class="page-hero page-hero-factory">
            <div class="page-hero-title">샘플 진행 현황 - {factory_name}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p class='page-caption'>{today:%Y년 %m월 %d일 %H:%M 기준}</p>",
        unsafe_allow_html=True,
    )
    _, preset_start, preset_end = render_period_selector(today, f"factory_{factory_name}")
    st.markdown(
        f"<p class='page-caption'>{preset_start:%Y년 %m월 %d일} ~ {preset_end:%Y년 %m월 %d일} "
        "샘플 접수일 기준</p>",
        unsafe_allow_html=True,
    )

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

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        stage_chart_df = pd.DataFrame(
            {
                "stage": STAGE_ORDER,
                "count": [int(stage_counts[stage]) for stage in STAGE_ORDER],
            }
        )
        stage_chart_df["label"] = stage_chart_df["count"].apply(
            lambda value: f"{value}건" if value > 0 else ""
        )
        fig = px.bar(
            stage_chart_df,
            x="stage",
            y="count",
            color="stage",
            text="label",
            category_orders={"stage": STAGE_ORDER},
            color_discrete_map=STAGE_COLORS,
        )
        fig.update_traces(
            texttemplate="<b>%{text}</b>",
            textposition="outside",
            textfont=dict(size=13, color="#111827"),
            cliponaxis=False,
            hovertemplate="%{x}: %{y}건<extra></extra>",
        )
        fig.update_layout(
            height=340,
            margin=dict(l=34, r=14, t=24, b=64),
            showlegend=False,
            bargap=0.35,
            uniformtext=dict(minsize=13, mode="show"),
            xaxis_title=None,
            yaxis_title=None,
            xaxis=dict(
                tickangle=-8,
                tickfont=dict(size=12, color="#111827"),
                automargin=True,
            ),
            yaxis=dict(
                rangemode="tozero",
                dtick=1,
                tickformat="d",
                tickfont=dict(size=12, color="#111827"),
                gridcolor="#dbe4f0",
                automargin=True,
            ),
        )
        render_chart_card(
            fig,
            title=f"{factory_name} 단계별 현황",
            chart_width=560,
            chart_height=320,
            card_width=600,
        )

        legend_html = "".join(
            f"<span><span class='legend-dot' style='background:{STAGE_COLORS.get(stage, '#d1d5db')}'></span>{stage} {int(stage_counts[stage])}건</span>"
            for stage in STAGE_ORDER
        )
        st.markdown(
            f"<div class='status-legend'>{legend_html}</div>",
            unsafe_allow_html=True,
        )

    with chart_col2:
        shipment_entries = build_duration_entries(target_df)
        render_duration_trend_chart(
            shipment_entries,
            width=480,
            card_width=600,
        )

    detail_df = target_df.drop(columns=["__stage__"])
    st.dataframe(
        detail_df,
        use_container_width=True,
        height=min(600, 200 + 35 * len(detail_df)),
    )


def render_limit_dashboard() -> None:
    set_query_params(view="limit")
    st.markdown(
        """
        <div class="page-hero">
            <div class="page-hero-title">한도 제작 현황</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    today = datetime.now()
    st.markdown(
        f"<p class='page-caption'>{today:%Y년 %m월 %d일 %H:%M 기준}</p>",
        unsafe_allow_html=True,
    )
    _, preset_start, preset_end = render_period_selector(today, "limit")

    (
        eligible_confirmed,
        eligible_ready,
        eligible_pending,
        confirmed_df,
        ready_df,
        pending_df,
    ) = prepare_limit_dashboard_data(
        st.session_state.df, preset_start, preset_end
    )
    st.markdown(
        f"<p class='page-caption'>{preset_start:%Y년 %m월 %d일} ~ {preset_end:%Y년 %m월 %d일} "
        "3차 이상 샘플 기준 (컨펌 등록 시 완료로 집계)</p>",
        unsafe_allow_html=True,
    )

    if confirmed_df.empty and ready_df.empty and pending_df.empty:
        st.info("선택한 기간에 관리할 한도 정보가 없습니다.")
        return

    confirmed_count = len(eligible_confirmed)
    eligible_ready_only = eligible_ready.drop(
        index=eligible_confirmed.index, errors="ignore"
    )
    ready_only = ready_df.drop(index=confirmed_df.index, errors="ignore")
    ready_count = len(eligible_ready_only)
    pending_count = len(eligible_pending)

    metrics_html = f"""
    <div class="limit-summary">
        <div class="limit-metric">
            <h4>컨펌 완료</h4>
            <strong>{confirmed_count}</strong><span style="margin-left:0.3rem;">건</span>
        </div>
        <div class="limit-metric">
            <h4>바로 발송 가능</h4>
            <strong>{ready_count}</strong><span style="margin-left:0.3rem;">건</span>
        </div>
        <div class="limit-metric">
            <h4>제작 필요</h4>
            <strong>{pending_count}</strong><span style="margin-left:0.3rem;">건</span>
        </div>
    </div>
    """
    st.markdown(metrics_html, unsafe_allow_html=True)

    ready_table = build_limit_view_table(ready_only)
    pending_table = build_limit_view_table(pending_df)
    confirmed_table = build_limit_view_table(
        confirmed_df,
        date_column="__limit_confirm_date__",
        date_label="한도 컨펌일",
    )

    st.subheader("한도 컨펌 완료 (시양산 대상)")
    if confirmed_table.empty:
        st.info("컨펌 완료된 한도 정보가 없습니다.")
    else:
        st.dataframe(
            confirmed_table,
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("바로 발송 가능한 한도")
    if ready_table.empty:
        st.info("사전 제작된 한도가 없습니다.")
    else:
        st.dataframe(
            ready_table,
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("제작이 필요한 한도")
    if pending_table.empty:
        st.success("모든 제품의 한도 제작이 완료되었습니다.")
    else:
        st.dataframe(
            pending_table,
            use_container_width=True,
            hide_index=True,
        )


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


def add_row(count: int = 1) -> None:
    count = max(1, int(count))
    if st.session_state.df.empty:
        st.session_state.df = pd.DataFrame(columns=list(DEFAULT_ROW.keys()))
    empty_row = {col: "" for col in st.session_state.df.columns}
    new_rows = pd.DataFrame([empty_row] * count)
    st.session_state.df = pd.concat(
        [st.session_state.df, new_rows],
        ignore_index=True,
    )
    st.session_state.status = f"빈 행 {count}개를 추가했습니다."
    persist_dataframe()


def delete_last_row(count: int = 1) -> None:
    count = max(1, int(count))
    if st.session_state.df.empty:
        st.info("삭제할 행이 없습니다.")
        return
    delete_count = min(count, len(st.session_state.df))
    st.session_state.df = st.session_state.df.iloc[:-delete_count].reset_index(drop=True)
    st.session_state.status = f"마지막 행 {delete_count}개를 삭제했습니다."
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
    inject_scroll_persistence()
    should_scroll_to_table = bool(st.session_state.get(SCROLL_TO_TABLE_FLAG, False))
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

    scroll_to_table_now = False
    selected_rows = get_selected_rows()
    with row_controls:
        st.subheader("행 관리")
        row_col1, row_col2, row_col3 = st.columns(3)
        if "row_add_count" in st.session_state:
            st.session_state["row_add_count"] = min(
                500, max(1, int(st.session_state["row_add_count"]))
            )
        add_count = int(
            row_col1.number_input(
                "추가 개수",
                min_value=1,
                max_value=500,
                value=1,
                step=1,
                key="row_add_count",
            )
        )
        if row_col1.button(f"{add_count}개 행 추가", use_container_width=True):
            add_row(add_count)
            scroll_to_table_now = True
        max_delete = max(1, len(st.session_state.df))
        if "row_delete_count" in st.session_state:
            st.session_state["row_delete_count"] = min(
                max_delete, max(1, int(st.session_state["row_delete_count"]))
            )
        delete_count = int(
            row_col2.number_input(
                "삭제 개수(뒤에서)",
                min_value=1,
                max_value=max_delete,
                value=min(1, max_delete),
                step=1,
                key="row_delete_count",
            )
        )
        if row_col2.button(
            f"마지막 {delete_count}개 행 삭제",
            use_container_width=True,
            disabled=st.session_state.df.empty,
        ):
            delete_last_row(delete_count)
            scroll_to_table_now = True
        if row_col3.button(
            f"선택 행 삭제 ({len(selected_rows)}개)",
            use_container_width=True,
            disabled=not selected_rows,
            help="데이터 테이블에서 체크한 행을 삭제합니다.",
        ):
            delete_selected_rows()
            scroll_to_table_now = True

    with history_controls:
        st.subheader("변경 이력")
        hist_col1, hist_col2 = st.columns(2)
        if hist_col1.button("되돌리기", use_container_width=True, disabled=not can_undo()):
            undo_changes()
            scroll_to_table_now = True
        if hist_col2.button("다시 실행", use_container_width=True, disabled=not can_redo()):
            redo_changes()
            scroll_to_table_now = True

    st.divider()

    st.markdown("<div id='data-table-anchor'></div>", unsafe_allow_html=True)
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

    if scroll_to_table_now or should_scroll_to_table:
        components.html(
            """
            <script>
            (() => {
              try {
                const hostDoc = window.parent.document;
                const anchor = hostDoc.getElementById("data-table-anchor");
                if (anchor) {
                  anchor.scrollIntoView({ behavior: "auto", block: "start" });
                }
              } catch (err) {}
            })();
            </script>
            """,
            height=0,
        )
        st.session_state[SCROLL_TO_TABLE_FLAG] = False


def build_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def build_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
        workbook = writer.book
        sheet = writer.sheets.get("Sheet1")
        if sheet is not None:
            max_row = len(df) + 1
            for col_idx, column in enumerate(df.columns, start=1):
                options = SELECT_COLUMN_OPTIONS.get(column)
                if not options:
                    continue
                valid_options = [opt.replace("\n", " / ") for opt in options if opt]
                if not valid_options:
                    continue
                formula = '"' + ",".join(option.replace('"', '""') for option in valid_options) + '"'
                dv = DataValidation(type="list", formula1=formula, allow_blank=True)
                column_letter = get_column_letter(col_idx)
                dv_range = f"{column_letter}2:{column_letter}{max_row}"
                dv.add(dv_range)
                sheet.add_data_validation(dv)
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
            background: #ffffff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    params = st.query_params
    view_param = normalize_query_value(params.get("view"), "sample")
    factory_param = normalize_query_value(params.get("factory"), "")
    stage_idx_param = normalize_query_value(params.get("stage_idx"), "")
    nav_param = normalize_query_value(params.get("nav"), "")

    factory_param_text = str(factory_param).strip()
    factory_param_key = factory_param_text.lower()
    if factory_param_text in LOCATION_DISPLAY_ORDER:
        resolved_factory = factory_param_text
    elif factory_param_key in FACTORY_QUERY_CODE_TO_NAME:
        resolved_factory = FACTORY_QUERY_CODE_TO_NAME[factory_param_key]
    else:
        resolved_factory = ""

    indent = "\u00A0\u00A0"
    nav_items: list[tuple[str, str, str | None]] = [
        ("샘플 종합 진도 현황", "sample", None),
        (f"{indent}C관", "factory", "C관"),
        (f"{indent}S관", "factory", "S관"),
        (f"{indent}FRP", "factory", "FRP"),
        ("한도 제작", "limit", None),
        ("관리 페이지", "admin", None),
    ]

    forced_nav_index: int | None = None
    if str(nav_param).strip():
        try:
            parsed_nav = int(str(nav_param).strip())
            if 0 <= parsed_nav < len(nav_items):
                forced_nav_index = parsed_nav
        except ValueError:
            forced_nav_index = None

    def initial_index() -> int:
        if forced_nav_index is not None:
            return forced_nav_index
        if view_param == "factory" and resolved_factory in LOCATION_DISPLAY_ORDER:
            return 1 + LOCATION_DISPLAY_ORDER.index(resolved_factory)
        if view_param == "limit":
            return 1 + len(LOCATION_DISPLAY_ORDER)
        if view_param == "admin":
            return 2 + len(LOCATION_DISPLAY_ORDER)
        return 0

    nav_key = "sidebar_nav_selection"
    if nav_key not in st.session_state:
        st.session_state[nav_key] = initial_index()
    last_nav_key = "__last_sidebar_nav_selection"
    if forced_nav_index is not None:
        st.session_state[nav_key] = forced_nav_index
        st.session_state[last_nav_key] = forced_nav_index
    previous_selection = st.session_state.get(last_nav_key, st.session_state[nav_key])
    query_selection = initial_index()
    radio_changed = st.session_state[nav_key] != previous_selection
    if not radio_changed and st.session_state[nav_key] != query_selection:
        st.session_state[nav_key] = query_selection

    selection = st.sidebar.radio(
        "페이지",
        list(range(len(nav_items))),
        format_func=lambda idx: nav_items[idx][0],
        key=nav_key,
    )
    st.session_state[last_nav_key] = selection

    page_type, factory_target = nav_items[selection][1:]

    if page_type == "sample":
        stage_idx_value: int | None = None
        if str(stage_idx_param).strip():
            try:
                parsed_idx = int(str(stage_idx_param).strip())
                if 0 <= parsed_idx < len(STAGE_ORDER):
                    stage_idx_value = parsed_idx
            except ValueError:
                stage_idx_value = None
        set_query_params(view="sample", stage_idx=stage_idx_value)
        render_sample_dashboard()
    elif page_type == "factory" and factory_target:
        set_query_params(
            view="factory",
            factory=FACTORY_NAME_TO_QUERY_CODE.get(factory_target, factory_target),
        )
        render_factory_detail_page(factory_target)
    elif page_type == "limit":
        set_query_params(view="limit")
        render_limit_dashboard()
    else:
        set_query_params(view="admin")
        render_admin_page()


if __name__ == "__main__":
    main()
