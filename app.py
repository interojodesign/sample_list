"""Streamlit 기반 샘플 리스트 관리 도구."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st


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
    if column == "DIA":
        return normalize_dia_value(text)
    return text


SELECT_COLUMN_OPTIONS = {
    "렌즈 구분": ["", "SPH", "TORIC", "프리즘"],
    "샘플 구분": ["", "1D", "M"],
    "함수율": ["", "38%", "43%", "45%", "55%"],
    "DIA": ["", "14.2", "14.5", "14.2\n14.5"],
    "착용기간": ["", "1D", "M"],
    "잉크 구분": ["", "액상", "파우더"],
    "제작 현황": ["", "대기", "진행중", "완료", "Drop"],
}

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
    df = df.fillna("")
    df = df.astype(str)
    return normalize_special_columns(df)


def normalize_special_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "DIA" in df.columns:
        df["DIA"] = df["DIA"].apply(normalize_dia_value)
    return df


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


if __name__ == "__main__":
    main()
