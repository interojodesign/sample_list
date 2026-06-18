"""Bootstrap wrapper for compiled app module."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
import hashlib
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


_REMOVED_PROCESS_COLUMNS = {
    "인쇄 완료일",
    "후공정 완료일",
    "후공정 완성일",
    "납기 요청일",
}
_RESTORED_OPTIONAL_COLUMNS = ("인쇄 시작일",)


def _drop_removed_process_columns(df):
    if df is None or not hasattr(df, "columns"):
        return df
    try:
        to_drop = [
            col
            for col in list(getattr(df, "columns", []))
            if str(col).strip() in _REMOVED_PROCESS_COLUMNS
        ]
        if not to_drop:
            return df
        return df.drop(columns=to_drop, errors="ignore")
    except Exception:
        return df


def _ensure_columns_present(df, columns):
    if df is None or not hasattr(df, "columns"):
        return df
    try:
        for col in columns:
            if col not in df.columns:
                df[col] = ""
    except Exception:
        return df
    return df


def _strip_removed_process_columns_from_defaults() -> None:
    default_row = getattr(compiled_app, "DEFAULT_ROW", None)
    if isinstance(default_row, dict):
        for key in list(default_row.keys()):
            if str(key).strip() in _REMOVED_PROCESS_COLUMNS:
                default_row.pop(key, None)

    shipment_cols = getattr(compiled_app, "SHIPMENT_DATE_COLUMNS", None)
    if isinstance(shipment_cols, (list, tuple)):
        cleaned = [
            col
            for col in list(shipment_cols)
            if str(col).strip() not in _REMOVED_PROCESS_COLUMNS
        ]
        if isinstance(shipment_cols, tuple):
            compiled_app.SHIPMENT_DATE_COLUMNS = tuple(cleaned)
        else:
            compiled_app.SHIPMENT_DATE_COLUMNS = cleaned


_strip_removed_process_columns_from_defaults()


def _parse_round_value(value) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except Exception:
        return None


def _clean_limit_popup_table(df):
    df = _drop_removed_process_columns(df)
    if df is None or not hasattr(df, "columns"):
        return df
    try:
        internal_cols = [
            col for col in list(df.columns)
            if str(col).strip().startswith("__")
        ]
        if internal_cols:
            df = df.drop(columns=internal_cols, errors="ignore")
    except Exception:
        return df
    return df

if hasattr(compiled_app, "load_local_file"):
    _orig_load_local_file = compiled_app.load_local_file

    def _load_local_file_without_removed_columns(path):
        return _drop_removed_process_columns(_orig_load_local_file(path))

    compiled_app.load_local_file = _load_local_file_without_removed_columns

if hasattr(compiled_app, "read_uploaded_file"):
    _orig_read_uploaded_file = compiled_app.read_uploaded_file

    def _read_uploaded_file_without_removed_columns(uploaded_file):
        return _drop_removed_process_columns(_orig_read_uploaded_file(uploaded_file))

    compiled_app.read_uploaded_file = _read_uploaded_file_without_removed_columns

# Pandas compatibility:
# - pandas < 3: DataFrame.applymap exists (deprecated)
# - pandas >= 3: DataFrame.applymap removed; use DataFrame.map
if hasattr(compiled_app, "sanitize_dataframe"):
    def _sanitize_dataframe_with_map_compat(df):
        pd_obj = compiled_app.pd
        if df.empty:
            base_columns = [
                col
                for col in list(compiled_app.DEFAULT_ROW.keys())
                if str(col).strip() not in _REMOVED_PROCESS_COLUMNS
            ]
            for col in _RESTORED_OPTIONAL_COLUMNS:
                if col not in base_columns:
                    base_columns.append(col)
            return pd_obj.DataFrame(columns=base_columns)

        df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed")]
        df = _drop_removed_process_columns(df)
        df = df.reset_index(drop=True)
        df = df.replace({pd_obj.NA: "", None: ""})
        df = df.fillna("")

        def _normalize_text(value):
            token = str(value).strip().lower()
            if token in {"none", "nan", "null", "-"}:
                return ""
            return str(value)

        text_df = df.astype(str)
        map_fn = getattr(text_df, "map", None)
        if callable(map_fn):
            df = map_fn(_normalize_text)
        else:
            df = text_df.applymap(_normalize_text)

        df = compiled_app.normalize_special_columns(df)
        df = compiled_app.normalize_select_columns(df)
        df = compiled_app.ensure_location_column(df)
        df[compiled_app.LOCATION_COLUMN] = df[compiled_app.LOCATION_COLUMN].apply(
            compiled_app.normalize_location_value
        )
        df = _ensure_columns_present(df, _RESTORED_OPTIONAL_COLUMNS)
        return _drop_removed_process_columns(df)

    compiled_app.sanitize_dataframe = _sanitize_dataframe_with_map_compat

# Keep selectbox options aligned with actual data values.
_base_normalize_dia_value = getattr(compiled_app, "normalize_dia_value", None)


def _clean_option_text(value) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.lower() in {"", "nan", "none", "null", "nat", "<na>", "-"}:
        return ""
    return text


def _normalize_dia_token(value) -> str:
    text = _clean_option_text(value)
    if not text:
        return ""

    if callable(_base_normalize_dia_value):
        try:
            text = _clean_option_text(_base_normalize_dia_value(text))
        except Exception:
            text = _clean_option_text(text)
    if not text:
        return ""

    numeric_candidate = text.replace(",", "")
    if re.fullmatch(r"\d+(?:\.\d+)?", numeric_candidate):
        try:
            parsed = float(numeric_candidate)
            rendered = f"{parsed:.4f}".rstrip("0").rstrip(".")
            if "." not in rendered:
                rendered += ".0"
            return rendered
        except Exception:
            return text
    return text


def _select_option_identity(column: str, value: str) -> str:
    canonical_fn = getattr(compiled_app, "canonical_select_key", None)
    if callable(canonical_fn):
        try:
            key = canonical_fn(column, value)
            if key is not None:
                return str(key)
        except Exception:
            pass
    return re.sub(r"\s+", "", str(value)).lower()


def _merge_select_options(column: str, base_options, dynamic_values) -> list[str]:
    merged = [""]
    seen = {""}
    raw_values = list(base_options or []) + list(dynamic_values or [])
    for raw in raw_values:
        text = _clean_option_text(raw)
        if not text:
            continue
        if column == "DIA":
            text = _normalize_dia_token(text)
            if not text:
                continue
        identity = _select_option_identity(column, text)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(text)
    return merged


def _build_dynamic_select_options(df):
    original = getattr(compiled_app, "SELECT_COLUMN_OPTIONS", None)
    if not isinstance(original, dict):
        return original

    updated = {}
    for column, base_options in original.items():
        extras = []
        if column == "DIA":
            extras.append("15.0")

        if df is not None and hasattr(df, "columns") and column in getattr(df, "columns", []):
            try:
                extras.extend(getattr(df[column], "tolist", lambda: list(df[column]))())
            except Exception:
                pass

        updated[column] = _merge_select_options(column, base_options, extras)
    return updated


def _run_with_dynamic_select_options(df, callback):
    original = getattr(compiled_app, "SELECT_COLUMN_OPTIONS", None)
    if not isinstance(original, dict):
        return callback(df)
    try:
        compiled_app.SELECT_COLUMN_OPTIONS = _build_dynamic_select_options(df)
        return callback(df)
    finally:
        compiled_app.SELECT_COLUMN_OPTIONS = original


if callable(_base_normalize_dia_value):
    def _normalize_dia_value_with_decimal(value):
        return _normalize_dia_token(value)

    compiled_app.normalize_dia_value = _normalize_dia_value_with_decimal

if hasattr(compiled_app, "SELECT_COLUMN_OPTIONS"):
    try:
        compiled_app.SELECT_COLUMN_OPTIONS = _build_dynamic_select_options(None)
    except Exception:
        pass

if hasattr(compiled_app, "build_column_config"):
    _orig_build_column_config = compiled_app.build_column_config

    def _build_column_config_with_dynamic_options(df):
        sanitized_df = _drop_removed_process_columns(df)
        config = _run_with_dynamic_select_options(sanitized_df, _orig_build_column_config)
        if isinstance(config, dict):
            for col in list(config.keys()):
                if str(col).strip() in _REMOVED_PROCESS_COLUMNS:
                    config.pop(col, None)
        return config

    compiled_app.build_column_config = _build_column_config_with_dynamic_options

if hasattr(compiled_app, "build_excel_bytes"):
    _orig_build_excel_bytes = compiled_app.build_excel_bytes

    def _build_excel_bytes_with_dynamic_options(df):
        return _run_with_dynamic_select_options(df, _orig_build_excel_bytes)

    compiled_app.build_excel_bytes = _build_excel_bytes_with_dynamic_options

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

    def _determine_stage_renamed(row, today, *args, **kwargs):
        # Re-define overdue logic:
        # - "납기 지연(발송일 변경)" date should not force delayed stage by itself.
        # - Delayed means due date has passed and status is not completed.
        # - Completed items must stay in "완료".
        def _row_get(obj, key, default=None):
            try:
                return obj.get(key, default)
            except Exception:
                try:
                    return obj[key]
                except Exception:
                    return default

        parse_date_fn = getattr(compiled_app, "parse_date", None)
        if not callable(parse_date_fn):
            return _normalize_stage_label(_orig_determine_stage(row, today, *args, **kwargs))

        raw = str(_row_get(row, "제작 현황", "") or "").strip()
        lowered = raw.lower()

        # Completion is always prioritized even if due date is in the past.
        if ("완료" in raw) or ("complete" in lowered):
            return _normalize_stage_label("완료")
        completion_columns = (
            "후공정 완료일",
            "완료일",
        )
        for col in completion_columns:
            completed_at = parse_date_fn(_row_get(row, col))
            if completed_at is not None:
                return _normalize_stage_label("완료")

        # Hold/drop should always stay in "보류", regardless of due-date state.
        if ("drop" in lowered) or ("보류" in raw):
            return _normalize_stage_label("보류")

        due_date = None
        due_columns = []
        delay_col = getattr(compiled_app, "DELAY_DATE_COLUMN", None)
        if isinstance(delay_col, str) and delay_col.strip():
            due_columns.append(delay_col.strip())
        due_columns.extend(list(getattr(compiled_app, "SHIPMENT_DATE_COLUMNS", []) or []))

        seen = set()
        for column in due_columns:
            if not isinstance(column, str):
                continue
            col = column.strip()
            if not col or col in seen:
                continue
            seen.add(col)
            parsed = parse_date_fn(_row_get(row, col))
            if parsed is not None:
                due_date = parsed
                break

        if due_date is None:
            if ("대기" in raw) or ("waiting" in lowered):
                return _normalize_stage_label("대기")
            if ("drop" in lowered) or ("보류" in raw):
                return _normalize_stage_label("보류")
            # Keep in-progress stage, then duplicate into "발송일 미확정" in dashboard preparation.
            if "진행" in raw:
                return _normalize_stage_label("진행중")
            return _normalize_stage_label("납기예정일 미확정")

        due_date_only = due_date.date() if hasattr(due_date, "date") else due_date
        today_date_only = today.date() if hasattr(today, "date") else today
        delta = (due_date_only - today_date_only).days

        # Overdue + not completed = delayed.
        if delta < 0:
            return _normalize_stage_label("납기지연")

        # Due within 3 days is always imminent (except completed handled above).
        if delta <= 3:
            return _normalize_stage_label("납기임박")

        if ("대기" in raw) or ("waiting" in lowered):
            return _normalize_stage_label("대기")
        if ("drop" in lowered) or ("보류" in raw):
            return _normalize_stage_label("보류")
        if "진행" in raw:
            return _normalize_stage_label("진행중")
        return _normalize_stage_label("진행중")

    compiled_app.determine_stage = _determine_stage_renamed

if hasattr(compiled_app, "prepare_dashboard_data") and hasattr(compiled_app, "pd"):
    _orig_prepare_dashboard_data = compiled_app.prepare_dashboard_data

    def _prepare_dashboard_data_with_missing_shipment_overlay(df, start_date, end_date):
        pd_obj = compiled_app.pd

        def _coerce_period_bound(value):
            try:
                parsed = pd_obj.to_datetime(value, errors="coerce")
                if not pd_obj.isna(parsed):
                    return parsed
            except Exception:
                pass
            return value

        result = _orig_prepare_dashboard_data(
            df,
            _coerce_period_bound(start_date),
            _coerce_period_bound(end_date),
        )
        try:
            if result is None:
                return result

            try:
                if (
                    df is not None
                    and hasattr(df, "columns")
                    and hasattr(df, "loc")
                    and "제작 현황" in df.columns
                ):
                    active_mask = df["제작 현황"].astype(str).str.contains("진행", na=False)
                    active_rows = df.loc[active_mask]
                    if not getattr(active_rows, "empty", True):
                        result = pd_obj.concat([result, active_rows], axis=0)
                        dedupe_cols = [
                            col
                            for col in list(df.columns)
                            if col in getattr(result, "columns", [])
                        ]
                        if dedupe_cols:
                            result = result.drop_duplicates(subset=dedupe_cols, keep="first")
            except Exception:
                pass

            if getattr(result, "empty", True):
                return result
            if "__stage__" not in getattr(result, "columns", []):
                result = result.copy()
                result["__stage__"] = ""

            determine_stage_fn = getattr(compiled_app, "determine_stage", None)
            if callable(determine_stage_fn):
                today = datetime.now()
                result = result.copy()
                result["__stage__"] = result.apply(
                    lambda row: _normalize_stage_label(determine_stage_fn(row, today)),
                    axis=1,
                )

            parse_date_fn = getattr(compiled_app, "parse_date", None)
            delay_col = getattr(compiled_app, "DELAY_DATE_COLUMN", None)
            shipment_cols = list(getattr(compiled_app, "SHIPMENT_DATE_COLUMNS", []) or [])
            candidate_cols = []
            for col in [delay_col, *shipment_cols]:
                if not isinstance(col, str):
                    continue
                name = col.strip()
                if not name:
                    continue
                # "납기 요청일" is not a shipment-finalized date; exclude from missing-shipment check.
                if "납기 요청" in name:
                    continue
                if name in result.columns and name not in candidate_cols:
                    candidate_cols.append(name)
            if not candidate_cols:
                for col in result.columns:
                    name = str(col).strip()
                    if not name:
                        continue
                    if ("발송" in name or "배송" in name) and ("요청" not in name):
                        candidate_cols.append(col)

            if not candidate_cols:
                return result

            stage_series = result["__stage__"].astype(str).str.strip()
            in_progress_mask = stage_series.eq("진행중")
            if not bool(in_progress_mask.any()):
                return result

            missing_idx = []
            progress_df = result.loc[in_progress_mask]
            for idx, row in progress_df.iterrows():
                has_shipment_date = False
                for col in candidate_cols:
                    value = row.get(col)
                    parsed = parse_date_fn(value) if callable(parse_date_fn) else pd_obj.to_datetime(value, errors="coerce")
                    if parsed is not None and not pd_obj.isna(parsed):
                        has_shipment_date = True
                        break
                if not has_shipment_date:
                    missing_idx.append(idx)

            if not missing_idx:
                return result

            overlay = result.loc[missing_idx].copy()
            overlay["__stage__"] = _NEW_MISSING_STAGE_LABEL
            result = pd_obj.concat([result, overlay], ignore_index=True)
        except Exception:
            return result
        return result

    compiled_app.prepare_dashboard_data = _prepare_dashboard_data_with_missing_shipment_overlay

if hasattr(compiled_app, "prepare_limit_dashboard_data") and hasattr(compiled_app, "pd"):
    _orig_prepare_limit_dashboard_data = compiled_app.prepare_limit_dashboard_data

    def _prepare_limit_dashboard_data_with_confirm_override(df, start_date, end_date):
        result = _orig_prepare_limit_dashboard_data(df, start_date, end_date)
        try:
            pd_obj = compiled_app.pd
            if not isinstance(result, tuple) or len(result) != 6:
                return result

            (
                eligible_confirmed,
                eligible_ready,
                eligible_pending,
                confirmed_df,
                ready_df,
                pending_df,
            ) = result

            limit_confirm_col = getattr(compiled_app, "LIMIT_CONFIRM_COLUMN", None)
            if not isinstance(limit_confirm_col, str) or not limit_confirm_col.strip():
                return result
            limit_confirm_col = limit_confirm_col.strip()
            parse_date_fn = getattr(compiled_app, "parse_date", None)

            def _empty_like(frame):
                if frame is None:
                    return pd_obj.DataFrame()
                return frame.iloc[0:0].copy()

            def _merge_unique(base, extra):
                if base is None and extra is None:
                    return pd_obj.DataFrame()
                if base is None:
                    return extra.copy()
                if extra is None or getattr(extra, "empty", True):
                    return base
                merged = pd_obj.concat([base, extra], axis=0)
                return merged.loc[~merged.index.duplicated(keep="first")].copy()

            def _extract_force_confirmed(*frames):
                valid_frames = [
                    frame
                    for frame in frames
                    if frame is not None and hasattr(frame, "columns") and hasattr(frame, "index")
                ]
                if not valid_frames:
                    return pd_obj.DataFrame()

                combined = pd_obj.concat(valid_frames, axis=0)
                if combined.empty:
                    return combined
                combined = combined.loc[~combined.index.duplicated(keep="first")].copy()

                if "__limit_confirm_date__" in combined.columns:
                    mask = combined["__limit_confirm_date__"].notna()
                elif limit_confirm_col in combined.columns:
                    if callable(parse_date_fn):
                        mask = combined[limit_confirm_col].apply(
                            lambda value: parse_date_fn(value) is not None
                        )
                    else:
                        mask = pd_obj.to_datetime(
                            combined[limit_confirm_col],
                            errors="coerce",
                        ).notna()
                else:
                    return combined.iloc[0:0]

                return combined.loc[mask].copy()

            forced_all = _extract_force_confirmed(confirmed_df, ready_df, pending_df)
            if forced_all.empty:
                return result

            forced_eligible = _extract_force_confirmed(
                eligible_confirmed,
                eligible_ready,
                eligible_pending,
            )

            confirmed_df_new = _merge_unique(confirmed_df, forced_all)
            ready_df_new = _merge_unique(ready_df, forced_all)
            pending_df_new = (
                pending_df.drop(index=forced_all.index, errors="ignore").copy()
                if pending_df is not None
                else _empty_like(forced_all)
            )

            eligible_confirmed_new = _merge_unique(eligible_confirmed, forced_eligible)
            eligible_ready_new = _merge_unique(eligible_ready, forced_eligible)
            eligible_pending_new = (
                eligible_pending.drop(index=forced_eligible.index, errors="ignore").copy()
                if eligible_pending is not None
                else _empty_like(forced_eligible)
            )

            return (
                eligible_confirmed_new,
                eligible_ready_new,
                eligible_pending_new,
                confirmed_df_new,
                ready_df_new,
                pending_df_new,
            )
        except Exception:
            return result

    compiled_app.prepare_limit_dashboard_data = _prepare_limit_dashboard_data_with_confirm_override

if hasattr(compiled_app, "render_limit_dashboard") and hasattr(compiled_app, "prepare_limit_dashboard_data"):
    _orig_render_limit_dashboard = compiled_app.render_limit_dashboard

    def _render_limit_dashboard_custom():
        st_obj = compiled_app.st
        pd_obj = getattr(compiled_app, "pd", None)
        parse_date_fn = getattr(compiled_app, "parse_date", None)
        set_query_params = getattr(compiled_app, "set_query_params", None)
        render_period_selector = getattr(compiled_app, "render_period_selector", None)
        prepare_limit_dashboard_data = getattr(compiled_app, "prepare_limit_dashboard_data", None)

        if not callable(render_period_selector) or not callable(prepare_limit_dashboard_data):
            return _orig_render_limit_dashboard()

        if callable(set_query_params):
            set_query_params(view="limit")

        st_obj.markdown(
            """
            <div class="page-hero">
                <div class="page-hero-title">한도 제작 현황</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        today = datetime.now()
        st_obj.markdown(
            f"<p class='page-caption'>{today:%Y년 %m월 %d일 %H:%M 기준}</p>",
            unsafe_allow_html=True,
        )

        _, preset_start, preset_end = render_period_selector(today, "limit")

        try:
            (
                eligible_confirmed,
                eligible_ready,
                eligible_pending,
                confirmed_df,
                ready_df,
                pending_df,
            ) = prepare_limit_dashboard_data(
                st_obj.session_state.df,
                preset_start,
                preset_end,
            )
        except Exception:
            return _orig_render_limit_dashboard()

        st_obj.markdown(
            (
                "<p class='page-caption'>"
                f"{preset_start:%Y년 %m월 %d일} ~ {preset_end:%Y년 %m월 %d일} "
                "한도 제작 기준: 차수 4차 이상 또는 렌즈 컨펌일 등록"
                "</p>"
            ),
            unsafe_allow_html=True,
        )

        if (
            getattr(confirmed_df, "empty", True)
            and getattr(ready_df, "empty", True)
            and getattr(pending_df, "empty", True)
        ):
            st_obj.info("선택한 기간에 관리할 한도 정보가 없습니다.")
            return

        def _to_datetime_value(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, date):
                return datetime.combine(value, datetime.min.time())
            try:
                if pd_obj is not None:
                    parsed = pd_obj.to_datetime(value, errors="coerce")
                    if not pd_obj.isna(parsed):
                        return parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed
            except Exception:
                return None
            return None

        def _parse_date_value(value):
            if callable(parse_date_fn):
                try:
                    parsed = parse_date_fn(value)
                    if parsed is not None:
                        return _to_datetime_value(parsed)
                except Exception:
                    pass
            return _to_datetime_value(value)

        def _merge_unique_frames(*frames):
            valid_frames = [
                frame
                for frame in frames
                if frame is not None and hasattr(frame, "index") and hasattr(frame, "columns")
            ]
            if not valid_frames:
                return pd_obj.DataFrame() if pd_obj is not None else None
            if pd_obj is None:
                return valid_frames[0]
            merged = pd_obj.concat(valid_frames, axis=0)
            return merged.loc[~merged.index.duplicated(keep="first")].copy()

        def _augment_pending_by_round_rules(base_df, pending_frame, ready_frame, confirmed_frame, eligible_pending_frame):
            if pd_obj is None:
                return pending_frame, eligible_pending_frame
            if base_df is None or getattr(base_df, "empty", True):
                return pending_frame, eligible_pending_frame

            start_bound = _to_datetime_value(preset_start)
            end_bound = _to_datetime_value(preset_end)
            if start_bound is None or end_bound is None:
                return pending_frame, eligible_pending_frame

            local = _drop_removed_process_columns(base_df.copy())
            if local is None or getattr(local, "empty", True):
                return pending_frame, eligible_pending_frame

            filter_columns = []
            filter_date_col = getattr(compiled_app, "FILTER_DATE_COLUMN", None)
            if isinstance(filter_date_col, str) and filter_date_col.strip() and filter_date_col in local.columns:
                filter_columns.append(filter_date_col.strip())

            for col in list(getattr(compiled_app, "SHIPMENT_DATE_COLUMNS", []) or []):
                if not isinstance(col, str):
                    continue
                name = col.strip()
                if name and name in local.columns and name not in filter_columns:
                    filter_columns.append(name)

            for fallback in ("발송 예정일", "배송/예정일", "발송예정일"):
                if fallback in local.columns and fallback not in filter_columns:
                    filter_columns.append(fallback)

            confirm_columns = []
            for col in (
                getattr(compiled_app, "LIMIT_CONFIRM_COLUMN", None),
                getattr(compiled_app, "LENS_CONFIRM_COLUMN", None),
                "한도 컨펌일",
                "렌즈 컨펌일",
                "시안 컨펌일",
            ):
                if not isinstance(col, str):
                    continue
                name = col.strip()
                if name and name in local.columns and name not in confirm_columns:
                    confirm_columns.append(name)

            exclude_idx = set()
            for frame in (pending_frame, ready_frame, confirmed_frame):
                if frame is not None and hasattr(frame, "index"):
                    exclude_idx.update(list(frame.index))

            extra_indices = []
            for idx, row in local.iterrows():
                if idx in exclude_idx:
                    continue

                round_value = _parse_round_value(row.get("차수"))
                if round_value is None:
                    continue

                lens_confirm_value = _parse_date_value(
                    row.get(getattr(compiled_app, "LENS_CONFIRM_COLUMN", "렌즈 컨펌일"))
                ) or _parse_date_value(row.get("렌즈 컨펌일"))
                include_by_rule = (round_value >= 4) or (lens_confirm_value is not None)
                if not include_by_rule:
                    continue

                in_selected_period = False
                for col in filter_columns:
                    parsed_date = _parse_date_value(row.get(col))
                    if parsed_date is None:
                        continue
                    if start_bound <= parsed_date <= end_bound:
                        in_selected_period = True
                        break

                if not in_selected_period:
                    continue

                extra_indices.append(idx)

            if not extra_indices:
                return pending_frame, eligible_pending_frame

            extras = local.loc[extra_indices].copy()
            pending_merged = _merge_unique_frames(pending_frame, extras)
            eligible_pending_merged = _merge_unique_frames(eligible_pending_frame, extras)
            return pending_merged, eligible_pending_merged

        source_df = getattr(st_obj.session_state, "df", None)
        pending_df_aug, eligible_pending_aug = _augment_pending_by_round_rules(
            source_df,
            pending_df,
            ready_df,
            confirmed_df,
            eligible_pending,
        )

        def _filter_pending_needed(frame, lens_confirm_columns):
            if frame is None or getattr(frame, "empty", True):
                return frame
            local = frame.copy()
            try:
                confirm_cols = [
                    col for col in list(lens_confirm_columns or [])
                    if isinstance(col, str) and col.strip()
                ]
                mask = local.apply(
                    lambda row: (
                        ((_parse_round_value(row.get("차수")) or -10**9) >= 4)
                        or any(
                            _parse_date_value(row.get(col)) is not None
                            for col in confirm_cols
                            if col in row.index
                        )
                    ),
                    axis=1,
                )
                return local.loc[mask].copy()
            except Exception:
                return local

        def _filter_by_required_date(frame, date_columns):
            if frame is None or getattr(frame, "empty", True):
                return frame
            cols = [col for col in list(date_columns or []) if isinstance(col, str) and col.strip()]
            if not cols:
                return frame
            local = frame.copy()
            try:
                mask = local.apply(
                    lambda row: any(_parse_date_value(row.get(col)) is not None for col in cols if col in row.index),
                    axis=1,
                )
                return local.loc[mask].copy()
            except Exception:
                return local

        confirmed_count = len(eligible_confirmed)
        eligible_ready_only = eligible_ready.drop(index=eligible_confirmed.index, errors="ignore")
        ready_only = ready_df.drop(index=confirmed_df.index, errors="ignore")

        lens_confirm_col = getattr(compiled_app, "LENS_CONFIRM_COLUMN", "렌즈 컨펌일")
        ready_date_columns = [lens_confirm_col, "렌즈 컨펌일"]
        eligible_ready_only = _filter_by_required_date(eligible_ready_only, ready_date_columns)
        ready_only = _filter_by_required_date(ready_only, ready_date_columns)
        ready_count = len(eligible_ready_only) if eligible_ready_only is not None else 0

        pending_df_aug = _filter_pending_needed(pending_df_aug, ready_date_columns)
        eligible_pending_aug = _filter_pending_needed(eligible_pending_aug, ready_date_columns)
        pending_count = len(eligible_pending_aug) if eligible_pending_aug is not None else 0

        metrics_html = (
            "<div class=\"limit-summary\">"
            f"<div class=\"limit-metric\"><h4>렌즈(STD) 컨펌 완료</h4><strong>{confirmed_count}</strong>"
            "<span style=\"margin-left:0.3rem;\">건</span></div>"
            f"<div class=\"limit-metric\"><h4>한도 바로 발송 가능</h4><strong>{ready_count}</strong>"
            "<span style=\"margin-left:0.3rem;\">건</span></div>"
            f"<div class=\"limit-metric\"><h4>한도 제작 필요</h4><strong>{pending_count}</strong>"
            "<span style=\"margin-left:0.3rem;\">건</span></div>"
            "</div>"
        )
        st_obj.markdown(metrics_html, unsafe_allow_html=True)

        def _has_any_date_value(row, columns) -> bool:
            for col in columns:
                if col in row.index and _parse_date_value(row.get(col)) is not None:
                    return True
            return False

        def _to_display_table(frame, columns_map, required_date_columns=None):
            if pd_obj is None:
                return frame
            required_date_columns = list(required_date_columns or [])
            column_names = [dst for _, dst in columns_map]

            if frame is None or getattr(frame, "empty", True):
                return pd_obj.DataFrame(columns=column_names)

            local = _clean_limit_popup_table(frame.copy())
            if local is None or getattr(local, "empty", True):
                return pd_obj.DataFrame(columns=column_names)

            if required_date_columns:
                mask = local.apply(
                    lambda row: _has_any_date_value(row, required_date_columns),
                    axis=1,
                )
                local = local.loc[mask].copy()
                if local.empty:
                    return pd_obj.DataFrame(columns=column_names)

            out = pd_obj.DataFrame(index=local.index)
            for src, dst in columns_map:
                out[dst] = local[src] if src in local.columns else ""

            date_like_columns = {"렌즈 컨펌일", "한도 컨펌일"}
            for col in [c for c in out.columns if c in date_like_columns]:
                out[col] = out[col].apply(
                    lambda value: (
                        _parse_date_value(value).strftime("%Y-%m-%d")
                        if _parse_date_value(value) is not None
                        else (
                            ""
                            if str(value).strip().lower() in {"", "nan", "none", "nat", "<na>"}
                            else str(value).strip()
                        )
                    )
                )

            out = out.fillna("")
            return out.reset_index(drop=True)

        confirmed_columns_map = [
            ("국가", "국가"),
            ("고객사", "고객사"),
            ("품명", "품명"),
            ("샘플 구분", "샘플구분"),
            ("차수", "차수"),
            ("렌즈 컨펌일", "렌즈 컨펌일"),
            ("한도 컨펌일", "한도 컨펌일"),
        ]
        ready_pending_columns_map = [
            ("국가", "국가"),
            ("고객사", "고객사"),
            ("품명", "품명"),
            ("샘플 구분", "샘플구분"),
            ("차수", "차수"),
            ("렌즈 컨펌일", "렌즈 컨펌일"),
            ("한도 제작", "한도제작"),
        ]

        limit_confirm_col = getattr(compiled_app, "LIMIT_CONFIRM_COLUMN", "한도 컨펌일")

        confirmed_table = _to_display_table(
            confirmed_df,
            confirmed_columns_map,
            required_date_columns=[limit_confirm_col, "한도 컨펌일"],
        )
        ready_table = _to_display_table(
            ready_only,
            ready_pending_columns_map,
            required_date_columns=[lens_confirm_col, "렌즈 컨펌일"],
        )
        pending_table = _to_display_table(
            pending_df_aug,
            ready_pending_columns_map,
        )

        st_obj.subheader("한도 컨펌 완료(시양산 대상)")
        if confirmed_table.empty:
            st_obj.info("한도 컨펌일이 등록된 항목이 없습니다.")
        else:
            st_obj.dataframe(confirmed_table, use_container_width=True, hide_index=True)

        st_obj.subheader("한도 바로 발송 가능")
        if ready_table.empty:
            st_obj.info("렌즈 컨펌일이 등록된 한도 바로 발송 가능 항목이 없습니다.")
        else:
            st_obj.dataframe(ready_table, use_container_width=True, hide_index=True)

        st_obj.subheader("한도 제작 필요")
        if pending_table.empty:
            st_obj.success("한도 제작 필요 항목이 없습니다.")
        else:
            st_obj.dataframe(pending_table, use_container_width=True, hide_index=True)

    compiled_app.render_limit_dashboard = _render_limit_dashboard_custom

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
                    y_axis_kwargs = {}
                    if is_detail_stage_chart:
                        if total_count <= 5:
                            y_top = max(5, max_stage_count)
                            y_axis_kwargs = {"tick0": 0, "dtick": 1}
                        elif total_count <= 10:
                            y_top = max(10, ((max_stage_count + 1) // 2) * 2)
                            y_axis_kwargs = {"tick0": 0, "dtick": 2}
                        else:
                            y_top = max(5, ((max_stage_count + 4) // 5) * 5)
                            y_axis_kwargs = {"tick0": 0, "dtick": 5}
                    fig.update_yaxes(
                        range=[-line_lift, y_top],
                        zeroline=True,
                        zerolinecolor="#111827",
                        zerolinewidth=1.2,
                        **y_axis_kwargs,
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

    def _render_sample_upload_box() -> None:
        st_obj = compiled_app.st
        upload_sig_key = "_sample_dashboard_applied_upload_sig"

        with st_obj.expander("샘플 리스트 엑셀 업로드", expanded=False):
            uploaded = st_obj.file_uploader(
                "sample-list.xlsx 파일 선택",
                type=["xlsx"],
                key="sample_dashboard_upload_file",
                help="업로드 즉시 대시보드 데이터에 반영됩니다.",
            )

            current_file = st_obj.session_state.get("current_file")
            current_name = Path(str(current_file)).name if current_file else "sample-list.xlsx"
            st_obj.caption(f"현재 반영 파일: `{current_name}`")

            if uploaded is None:
                return

            raw_bytes = uploaded.getvalue()
            file_sig = f"{uploaded.name}:{uploaded.size}:{hashlib.sha256(raw_bytes).hexdigest()}"
            if st_obj.session_state.get(upload_sig_key) == file_sig:
                st_obj.info("이미 반영된 동일 파일입니다.")
                return

            try:
                uploaded_df = compiled_app.read_uploaded_file(uploaded)
                sanitized_df = compiled_app.sanitize_dataframe(uploaded_df)
            except Exception as exc:
                st_obj.error("엑셀 파일을 읽을 수 없습니다. sample-list 형식(.xlsx)인지 확인해 주세요.")
                st_obj.caption(str(exc))
                return

            target_path = ROOT_DIR / "sample-list.xlsx"
            try:
                target_path.write_bytes(raw_bytes)
            except Exception as exc:
                st_obj.error("업로드 파일 저장에 실패했습니다.")
                st_obj.caption(str(exc))
                return

            st_obj.session_state["df"] = sanitized_df
            st_obj.session_state["current_file"] = str(target_path)
            st_obj.session_state["status"] = f"{uploaded.name} 업로드 반영 완료"
            st_obj.session_state["last_uploaded_sig"] = file_sig
            st_obj.session_state[upload_sig_key] = file_sig

            remember_last_file = getattr(compiled_app, "remember_last_file", None)
            if callable(remember_last_file):
                try:
                    remember_last_file(target_path)
                except Exception:
                    pass

            reset_history = getattr(compiled_app, "reset_history", None)
            if callable(reset_history):
                try:
                    reset_history()
                except Exception:
                    pass

            st_obj.success("업로드 반영이 완료되었습니다. 화면을 새로고칩니다.")
            st_obj.rerun()

    def _render_sample_dashboard_with_hint_relocated():
        st_obj = compiled_app.st
        original_caption = st_obj.caption
        original_dataframe = getattr(st_obj, "dataframe", None)
        original_data_editor = getattr(st_obj, "data_editor", None)
        suppressed_hint = {"value": False}

        def _caption_override(body=None, *args, **kwargs):
            if str(body or "").strip() == _STATUS_HINT_TEXT:
                suppressed_hint["value"] = True
                return None
            return original_caption(body, *args, **kwargs)

        def _display_data_without_removed_columns(data):
            return _drop_removed_process_columns(data)

        if callable(original_dataframe):
            def _dataframe_without_removed_columns(data=None, *args, **kwargs):
                return original_dataframe(
                    _display_data_without_removed_columns(data),
                    *args,
                    **kwargs,
                )

            st_obj.dataframe = _dataframe_without_removed_columns

        if callable(original_data_editor):
            def _data_editor_without_removed_columns(data=None, *args, **kwargs):
                return original_data_editor(
                    _display_data_without_removed_columns(data),
                    *args,
                    **kwargs,
                )

            st_obj.data_editor = _data_editor_without_removed_columns

        st_obj.caption = _caption_override
        try:
            result = _orig_render_sample_dashboard()
        finally:
            st_obj.caption = original_caption
            if callable(original_dataframe):
                st_obj.dataframe = original_dataframe
            if callable(original_data_editor):
                st_obj.data_editor = original_data_editor

        left_col, right_col = st_obj.columns([1.35, 0.95])
        with left_col:
            upload_panel = st_obj.container(key="sample_upload_panel")
            with upload_panel:
                _render_sample_upload_box()

        if suppressed_hint["value"]:
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
        orig_dataframe = getattr(st_obj, "dataframe", None)
        orig_data_editor = getattr(st_obj, "data_editor", None)
        orig_render_chart_card = getattr(compiled_app, "render_chart_card", None)
        orig_render_duration_trend_chart = getattr(compiled_app, "render_duration_trend_chart", None)
        chart_row_adjusted = False
        table_probe = {
            "called": False,
            "rows": 0,
            "cols": 0,
            "suspicious": False,
        }

        def _build_factory_detail_fallback_df():
            pd_obj = getattr(compiled_app, "pd", None)
            prepare_dashboard_data = getattr(compiled_app, "prepare_dashboard_data", None)
            if pd_obj is None or not callable(prepare_dashboard_data):
                return None

            today = datetime.now()
            start = today - timedelta(days=30)
            end = today
            prefix = f"factory_{factory_name}"
            for key, value in dict(getattr(st_obj, "session_state", {}) or {}).items():
                if prefix not in str(key) or "date_range" not in str(key):
                    continue
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    try:
                        start_candidate = pd_obj.to_datetime(value[0], errors="coerce")
                        end_candidate = pd_obj.to_datetime(value[1], errors="coerce")
                        if (not pd_obj.isna(start_candidate)) and (not pd_obj.isna(end_candidate)):
                            start = start_candidate.to_pydatetime()
                            end = end_candidate.to_pydatetime()
                            break
                    except Exception:
                        continue

            source_df = getattr(st_obj.session_state, "df", None)
            if source_df is None:
                return None
            prepared = prepare_dashboard_data(source_df, start, end)
            location_col = getattr(compiled_app, "LOCATION_COLUMN", "샘플제작 공장위치")
            if (
                prepared is None
                or not hasattr(prepared, "columns")
                or not hasattr(prepared, "loc")
                or location_col not in prepared.columns
            ):
                return None

            detail = prepared.loc[
                prepared[location_col].astype(str).str.strip() == str(factory_name).strip()
            ].copy()
            if detail.empty:
                return detail
            detail = detail.drop(columns=["__stage__", "__filter_date__"], errors="ignore")
            detail = _drop_removed_process_columns(detail)
            if detail is not None and hasattr(detail, "columns"):
                internal_cols = [
                    col for col in list(detail.columns)
                    if str(col).strip().startswith("__")
                ]
                if internal_cols:
                    detail = detail.drop(columns=internal_cols, errors="ignore")
            return detail

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
                        range=[0, y_top] if y_top is not None else None,
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
        if callable(orig_dataframe):
            def _dataframe_without_removed_columns(data=None, *args, **kwargs):
                cleaned = _drop_removed_process_columns(data)
                table_probe["called"] = True
                if cleaned is None or not hasattr(cleaned, "shape") or not hasattr(cleaned, "columns"):
                    table_probe["suspicious"] = True
                    fallback = _build_factory_detail_fallback_df()
                    if fallback is not None and hasattr(fallback, "empty") and not fallback.empty:
                        cleaned = fallback
                if cleaned is not None and hasattr(cleaned, "shape") and hasattr(cleaned, "columns"):
                    try:
                        rows, cols = cleaned.shape
                    except Exception:
                        rows, cols = 0, 0
                    table_probe["rows"] = int(rows or 0)
                    table_probe["cols"] = int(cols or 0)
                    try:
                        normalized_cols = [str(col).strip() for col in list(cleaned.columns)]
                        if len([col for col in normalized_cols if col]) <= 1:
                            table_probe["suspicious"] = True
                    except Exception:
                        pass
                    try:
                        if table_probe["rows"] <= 1 and table_probe["cols"] <= 2:
                            sample_cells = [
                                str(value).strip().lower()
                                for value in cleaned.astype(str).head(1).to_numpy().ravel().tolist()
                            ]
                            if any(cell == "empty" for cell in sample_cells):
                                table_probe["suspicious"] = True
                    except Exception:
                        pass
                    if bool(table_probe["suspicious"]):
                        fallback = _build_factory_detail_fallback_df()
                        if fallback is not None and hasattr(fallback, "empty") and not fallback.empty:
                            cleaned = fallback
                return orig_dataframe(cleaned, *args, **kwargs)

            st_obj.dataframe = _dataframe_without_removed_columns
        if callable(orig_data_editor):
            def _data_editor_without_removed_columns(data=None, *args, **kwargs):
                return orig_data_editor(
                    _drop_removed_process_columns(data),
                    *args,
                    **kwargs,
                )

            st_obj.data_editor = _data_editor_without_removed_columns
        if callable(orig_render_chart_card):
            compiled_app.render_chart_card = _render_chart_card_override
        if callable(orig_render_duration_trend_chart):
            compiled_app.render_duration_trend_chart = _render_duration_trend_chart_override
        result = None
        try:
            result = _orig_render_factory_detail_page(factory_name)
        finally:
            st_obj.columns = orig_columns
            if callable(orig_dataframe):
                st_obj.dataframe = orig_dataframe
            if callable(orig_data_editor):
                st_obj.data_editor = orig_data_editor
            if callable(orig_render_chart_card):
                compiled_app.render_chart_card = orig_render_chart_card
            if callable(orig_render_duration_trend_chart):
                compiled_app.render_duration_trend_chart = orig_render_duration_trend_chart
        should_render_fallback = (not table_probe["called"]) or bool(table_probe["suspicious"])
        if should_render_fallback:
            try:
                detail = _build_factory_detail_fallback_df()
                if detail is not None and hasattr(detail, "empty") and not detail.empty:
                    st_obj.caption("상세 목록을 다시 불러왔습니다.")
                    st_obj.dataframe(
                        detail,
                        use_container_width=True,
                        height=min(600, 200 + 35 * len(detail)),
                    )
            except Exception:
                pass
        return result

    compiled_app.render_factory_detail_page = _render_factory_detail_page_with_fixed_stage_width

# Final safety net: strip duplicated "총 N건" labels from Plotly HTML payload.
if hasattr(compiled_app, "components") and hasattr(compiled_app.components, "html"):
    _components_api = compiled_app.components
    _current_components_html = _components_api.html

    def _resolve_base_components_html(func):
        current = func
        visited = set()
        while callable(current):
            current_id = id(current)
            if current_id in visited:
                break
            visited.add(current_id)

            next_func = getattr(current, "__sample_list_base_html__", None)
            if callable(next_func) and next_func is not current:
                current = next_func
                continue

            # Legacy unwrapping: older wrapper versions chained through a module-global
            # `_orig_components_html`, which could stack deeply across reruns.
            legacy_next = None
            try:
                globals_dict = getattr(current, "__globals__", None)
                if isinstance(globals_dict, dict):
                    legacy_next = globals_dict.get("_orig_components_html")
            except Exception:
                legacy_next = None
            if callable(legacy_next) and legacy_next is not current:
                current = legacy_next
                continue

            break
        return current if callable(current) else None

    _base_components_html = _resolve_base_components_html(_current_components_html)

    if callable(_base_components_html):
        def _components_html_without_total_duplicates(
            html_str,
            *args,
            _base_html=_base_components_html,
            **kwargs,
        ):
            try:
                if isinstance(html_str, str):
                    # Disable stale table scroll restoration script which can reopen
                    # detail tables at invalid scroll positions and show blank rows.
                    html_str = re.sub(
                        r"<script>\s*\(\(\)\s*=>\s*\{.*?sample-manager-scroll-v1.*?\}\)\(\);\s*</script>",
                        "",
                        html_str,
                        flags=re.DOTALL,
                    )
                    # Disable legacy anchor auto-scroll helper for the same reason.
                    html_str = re.sub(
                        r"<script>\s*\(\(\)\s*=>\s*\{.*?data-table-anchor.*?\}\)\(\);\s*</script>",
                        "",
                        html_str,
                        flags=re.DOTALL,
                    )
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
            return _base_html(html_str, *args, **kwargs)

        _components_html_without_total_duplicates.__sample_list_base_html__ = _base_components_html
        _components_api.html = _components_html_without_total_duplicates


def _inject_runtime_dom_tweaks() -> None:
    # Intentionally no-op: DOM tweaks disabled in favor of render-level adjustments.
    return


def _ensure_default_route_to_sample_dashboard() -> None:
    """When opening bare root URL, default to sample dashboard instead of admin."""
    try:
        st_obj = compiled_app.st
        params = st_obj.query_params
        # Apply a one-time bootstrap redirect to sample dashboard on fresh app entry.
        # This also fixes cases where stale `view=admin` remains in browser query params.
        if bool(st_obj.session_state.get("_default_sample_route_bootstrapped", False)):
            return
        has_deep_link = any(key in params for key in ("factory", "stage_idx"))
        if has_deep_link:
            st_obj.session_state["_default_sample_route_bootstrapped"] = True
            return
        st_obj.session_state["sidebar_nav_selection"] = 0
        st_obj.session_state["__last_sidebar_nav_selection"] = 0
        st_obj.session_state["_default_sample_route_bootstrapped"] = True
        params.clear()
        params["view"] = "sample"
        params["nav"] = "0"
    except Exception:
        pass


def _hide_admin_page_in_sidebar() -> None:
    try:
        sidebar_obj = compiled_app.st.sidebar
        current_radio = getattr(sidebar_obj, "radio", None)
        if not callable(current_radio):
            return

        base_radio = getattr(current_radio, "__sample_list_base_radio__", None)
        orig_radio = base_radio if callable(base_radio) else current_radio

        def _radio_without_admin(label, options, *args, _base_radio=orig_radio, **kwargs):
            key = kwargs.get("key")
            if key == "sidebar_nav_selection":
                try:
                    option_list = list(options)
                    format_func = kwargs.get("format_func")
                    filtered = []
                    for opt in option_list:
                        label_text = ""
                        if callable(format_func):
                            try:
                                label_text = str(format_func(opt)).strip()
                            except Exception:
                                label_text = ""
                        if label_text == "관리 페이지":
                            continue
                        filtered.append(opt)

                    if filtered and len(filtered) < len(option_list):
                        state = compiled_app.st.session_state
                        if state.get(key) not in filtered:
                            state[key] = filtered[0]
                        options = filtered
                except Exception:
                    pass
            return _base_radio(label, options, *args, **kwargs)

        _radio_without_admin.__sample_list_base_radio__ = orig_radio
        sidebar_obj.radio = _radio_without_admin
    except Exception:
        pass


def _disable_admin_page_render() -> None:
    current_render_admin = getattr(compiled_app, "render_admin_page", None)
    if not callable(current_render_admin):
        return

    base_render_admin = getattr(current_render_admin, "__sample_list_base_admin__", None)
    orig_render_admin = base_render_admin if callable(base_render_admin) else current_render_admin

    def _render_admin_page_disabled(_base_admin=orig_render_admin):
        st_obj = compiled_app.st
        st_obj.info("관리 페이지는 비활성화되었습니다. 왼쪽 하단의 엑셀 업로드로 데이터를 반영해 주세요.")
        try:
            if hasattr(compiled_app, "set_query_params"):
                compiled_app.set_query_params(view="sample", stage_idx=None)
        except Exception:
            pass
        render_sample_dashboard = getattr(compiled_app, "render_sample_dashboard", None)
        if callable(render_sample_dashboard):
            return render_sample_dashboard()
        return _base_admin()

    _render_admin_page_disabled.__sample_list_base_admin__ = orig_render_admin
    compiled_app.render_admin_page = _render_admin_page_disabled


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
    _hide_admin_page_in_sidebar()
    _disable_admin_page_render()
    _ensure_default_route_to_sample_dashboard()
    compiled_app.main()
    _inject_runtime_dom_tweaks()
else:
    raise AttributeError("Compiled app module has no main()")
