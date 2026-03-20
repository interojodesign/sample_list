"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const state = {
    columns: [],
    rows: [],
    fileHandle: null,
    fileFormat: "csv",
    currentFileName: "새 문서",
  };

  const defaultColumns = [
    "국가",
    "고객사",
    "담당자",
    "렌즈 구분",
    "샘플 구분",
    "함수율",
    "DIA",
    "잉크 구분",
    "품명",
    "차수",
    "샘플 접수일",
    "시안 컨펌일",
    "인쇄 시작일",
    "인쇄 완료일",
    "후공정 완성일",
    "납기 요청일",
    "배송/예정일",
    "제작 현황",
    "샘플제작 공장위치",
  ];

  const defaultRow = {
    국가: "일본",
    고객사: "Sincere",
    담당자: "송미정 대리",
    "렌즈 구분": "SPH",
    "샘플 구분": "ID",
    함수율: "45%",
    DIA: "14.2",
    "잉크 구분": "색상",
    품명: "실리콘 제한 렌즈 2종",
    차수: "2",
    "샘플 접수일": "25.10.02",
    "시안 컨펌일": "25.10.04",
    "인쇄 시작일": "25.10.04",
    "인쇄 완료일": "25.10.08",
    "후공정 완성일": "25.10.09",
    "납기 요청일": "25.10.09",
    "배송/예정일": "25.10.10",
    "제작 현황": "대기",
    "샘플제작 공장위치": "미지정",
  };

  const refs = {
    status: document.getElementById("status"),
    fileInput: document.getElementById("file-input"),
    newTableBtn: document.getElementById("new-table-btn"),
    downloadCsvBtn: document.getElementById("download-csv-btn"),
    downloadXlsxBtn: document.getElementById("download-xlsx-btn"),
    openPickerBtn: document.getElementById("open-picker-btn"),
    saveHandleBtn: document.getElementById("save-file-handle-btn"),
    addColumnForm: document.getElementById("add-column-form"),
    newColumnInput: document.getElementById("new-column-name"),
    renameColumnForm: document.getElementById("rename-column-form"),
    renameColumnSelect: document.getElementById("rename-column-select"),
    renameColumnValue: document.getElementById("rename-column-value"),
    deleteColumnForm: document.getElementById("delete-column-form"),
    deleteColumnSelect: document.getElementById("delete-column-select"),
    addRowBtn: document.getElementById("add-row-btn"),
    deleteRowBtn: document.getElementById("delete-row-btn"),
    tableHead: document.querySelector("#data-table thead"),
    tableBody: document.querySelector("#data-table tbody"),
  };

  init();

  function init() {
    refs.fileInput.addEventListener("change", onFileInputChange);
    refs.newTableBtn.addEventListener("click", buildDefaultTable);
    refs.downloadCsvBtn.addEventListener("click", () =>
      downloadFile("csv")
    );
    refs.downloadXlsxBtn.addEventListener("click", () =>
      downloadFile("xlsx")
    );
    refs.openPickerBtn.addEventListener("click", openWithFilePicker);
    refs.saveHandleBtn.addEventListener("click", saveThroughHandle);
    refs.addColumnForm.addEventListener("submit", onAddColumn);
    refs.renameColumnForm.addEventListener("submit", onRenameColumn);
    refs.deleteColumnForm.addEventListener("submit", onDeleteColumn);
    refs.addRowBtn.addEventListener("click", addEmptyRow);
    refs.deleteRowBtn.addEventListener("click", deleteLastRow);
    refs.tableBody.addEventListener("input", onCellInput);
    refs.renameColumnSelect.addEventListener(
      "change",
      onRenameColumnSelectChange
    );

    buildDefaultTable();
  }

  function buildDefaultTable() {
    state.columns = buildColumnsFromLabels(defaultColumns);
    state.rows = [
      {
        id: makeId("row"),
        values: mapRowValues(state.columns, defaultRow),
      },
    ];
    state.fileHandle = null;
    state.fileFormat = "csv";
    state.currentFileName = "새 문서";
    refreshUI("초기 표를 불러왔습니다.");
  }

  function mapRowValues(columns, source) {
    const values = {};
    columns.forEach((col) => {
      values[col.id] = source[col.label] ?? "";
    });
    return values;
  }

  function buildColumnsFromLabels(labels) {
    const seen = new Set();
    return labels.map((rawLabel, idx) => {
      const label =
        typeof rawLabel === "string" && rawLabel.trim()
          ? rawLabel.trim()
          : `열 ${idx + 1}`;
      const base = slugify(label) || `col_${idx + 1}`;
      let id = base;
      let counter = 1;
      while (seen.has(id)) {
        id = `${base}_${counter++}`;
      }
      seen.add(id);
      return { id, label };
    });
  }

  function refreshUI(statusMessage) {
    renderTable();
    populateColumnSelectors();
    if (statusMessage) {
      setStatus(statusMessage);
    }
  }

  function renderTable() {
    if (!state.columns.length) {
      refs.tableHead.innerHTML = "";
      refs.tableBody.innerHTML =
        '<tr><td class="empty" colspan="1">열이 없습니다. 열을 추가하거나 파일을 불러오세요.</td></tr>';
      return;
    }

    const headerHtml = `<tr>${state.columns
      .map((col) => `<th>${escapeHtml(col.label)}</th>`)
      .join("")}</tr>`;
    refs.tableHead.innerHTML = headerHtml;

    if (!state.rows.length) {
      const emptyRow = `<tr><td class="empty" colspan="${state.columns.length}">데이터가 없습니다. 행을 추가하거나 파일을 불러오세요.</td></tr>`;
      refs.tableBody.innerHTML = emptyRow;
      return;
    }

    const bodyHtml = state.rows
      .map(
        (row) =>
          `<tr>${state.columns
            .map((col) => {
              const value = row.values[col.id] ?? "";
              return `<td contenteditable="true" data-row-id="${row.id}" data-col-id="${col.id}">${escapeHtml(
                value
              )}</td>`;
            })
            .join("")}</tr>`
      )
      .join("");
    refs.tableBody.innerHTML = bodyHtml;
  }

  function populateColumnSelectors() {
    const options = state.columns
      .map(
        (col) =>
          `<option value="${col.id}">${escapeHtml(col.label)}</option>`
      )
      .join("");
    refs.renameColumnSelect.innerHTML = options;
    refs.deleteColumnSelect.innerHTML = options;

    const disabled = state.columns.length === 0;
    refs.renameColumnSelect.disabled = disabled;
    refs.deleteColumnSelect.disabled = disabled;
    refs.renameColumnValue.disabled = disabled;
  }

  function onFileInputChange(event) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    loadFile(file).catch(() =>
      setStatus("파일을 불러오지 못했습니다. 다시 시도해 주세요.")
    );
    event.target.value = "";
  }

  function loadFile(file) {
    const extension = getExtension(file.name);
    if (extension === "xlsx" || extension === "xls") {
      return loadExcelFile(file);
    }
    return loadCsvFile(file);
  }

  function loadCsvFile(file) {
    return new Promise((resolve, reject) => {
      Papa.parse(file, {
        header: true,
        skipEmptyLines: "greedy",
        complete: (results) => {
          const headers = results.meta.fields?.filter(Boolean) ?? [];
          const data = sanitizeRows(results.data, headers);
          rebuildStateFromImport(headers, data);
          state.fileFormat = "csv";
          state.currentFileName = file.name;
          state.fileHandle = null;
          refreshUI(`${file.name} 불러오기 완료`);
          resolve();
        },
        error: (error) => {
          console.error(error);
          alert("CSV 파일을 읽는 중 오류가 발생했습니다.");
          reject(error);
        },
      });
    });
  }

  function loadExcelFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const data = new Uint8Array(event.target.result);
          const workbook = XLSX.read(data, { type: "array" });
          const sheetName = workbook.SheetNames[0];
          const sheet = workbook.Sheets[sheetName];
          const json = XLSX.utils.sheet_to_json(sheet, { defval: "" });
          const headers = extractHeadersFromSheet(sheet);
          rebuildStateFromImport(headers, json);
          state.fileFormat = "xlsx";
          state.currentFileName = file.name;
          state.fileHandle = null;
          refreshUI(`${file.name} 불러오기 완료`);
          resolve();
        } catch (error) {
          console.error(error);
          alert("엑셀 파일을 읽는 중 오류가 발생했습니다.");
          reject(error);
        }
      };
      reader.onerror = () => {
        reject(reader.error);
      };
      reader.readAsArrayBuffer(file);
    });
  }

  function extractHeadersFromSheet(sheet) {
    if (!sheet || !sheet["!ref"]) {
      return [];
    }
    const range = XLSX.utils.decode_range(sheet["!ref"]);
    const headers = [];
    for (let c = range.s.c; c <= range.e.c; c += 1) {
      const cellAddress = XLSX.utils.encode_cell({ r: range.s.r, c });
      const cell = sheet[cellAddress];
      headers.push(cell ? String(cell.v) : `열 ${c + 1}`);
    }
    return headers;
  }

  function sanitizeRows(rows, headers) {
    return rows
      .map((row) => {
        const sanitized = {};
        headers.forEach((header) => {
          sanitized[header] = row[header] ?? "";
        });
        return sanitized;
      })
      .filter((row) =>
        Object.values(row).some(
          (value) => value !== null && String(value).trim() !== ""
        )
      );
  }

  function rebuildStateFromImport(headers, dataRows) {
    const labels =
      headers && headers.length
        ? headers
        : Object.keys(dataRows[0] ?? {}).map((key, index) =>
            key ? String(key) : `열 ${index + 1}`
          );
    state.columns = buildColumnsFromLabels(labels);
    state.rows =
      dataRows.length > 0
        ? dataRows.map((row) => ({
            id: makeId("row"),
            values: mapRowValues(state.columns, row),
          }))
        : [
            {
              id: makeId("row"),
              values: mapRowValues(state.columns, {}),
            },
          ];
  }

  function onAddColumn(event) {
    event.preventDefault();
    const label = refs.newColumnInput.value.trim();
    if (!label) {
      return;
    }
    if (state.columns.some((col) => col.label === label)) {
      alert("같은 이름의 열이 이미 존재합니다.");
      return;
    }
    const id = generateUniqueColumnId(label);
    state.columns.push({ id, label });
    state.rows.forEach((row) => {
      row.values[id] = "";
    });
    refs.newColumnInput.value = "";
    refreshUI("열이 추가되었습니다.");
  }

  function onRenameColumn(event) {
    event.preventDefault();
    const targetId = refs.renameColumnSelect.value;
    const newLabel = refs.renameColumnValue.value.trim();
    if (!targetId || !newLabel) {
      return;
    }
    const duplicate = state.columns.find(
      (col) => col.label === newLabel && col.id !== targetId
    );
    if (duplicate) {
      alert("같은 이름의 열이 이미 있습니다.");
      return;
    }
    const column = state.columns.find((col) => col.id === targetId);
    if (column) {
      column.label = newLabel;
      refs.renameColumnValue.value = "";
      refreshUI("열 이름을 변경했습니다.");
    }
  }

  function onDeleteColumn(event) {
    event.preventDefault();
    const targetId = refs.deleteColumnSelect.value;
    if (!targetId) {
      return;
    }
    if (
      !confirm(
        "선택한 열과 해당 데이터가 모두 삭제됩니다. 계속하시겠습니까?"
      )
    ) {
      return;
    }
    state.columns = state.columns.filter((col) => col.id !== targetId);
    state.rows.forEach((row) => {
      delete row.values[targetId];
    });
    refreshUI("열을 삭제했습니다.");
  }

  function addEmptyRow() {
    if (!state.columns.length) {
      alert("먼저 최소 한 개의 열을 만들어 주세요.");
      return;
    }
    const values = {};
    state.columns.forEach((col) => {
      values[col.id] = "";
    });
    state.rows.push({ id: makeId("row"), values });
    refreshUI("행을 추가했습니다.");
  }

  function deleteLastRow() {
    if (!state.rows.length) {
      return;
    }
    state.rows.pop();
    refreshUI("마지막 행을 삭제했습니다.");
  }

  function onCellInput(event) {
    const cell = event.target.closest("td[data-row-id][data-col-id]");
    if (!cell) {
      return;
    }
    const row = state.rows.find((r) => r.id === cell.dataset.rowId);
    if (!row) {
      return;
    }
    row.values[cell.dataset.colId] = cell.textContent.replace(/\u00A0/g, " ");
  }

  function downloadFile(format) {
    if (!state.columns.length) {
      alert("저장할 열이 없습니다.");
      return;
    }
    const blob =
      format === "xlsx" ? buildExcelBlob() : buildCsvBlob();
    const filename = buildDownloadFileName(format);
    triggerDownload(blob, filename);
    setStatus(`${filename} 저장 완료 (다운로드)`);
  }

  function buildDownloadFileName(format) {
    const base =
      state.currentFileName?.replace(/\.[^.]+$/, "") || "sample-list";
    return `${base}.${format === "xlsx" ? "xlsx" : "csv"}`;
  }

  function buildCsvBlob() {
    const data = toObjectArray();
    const csv = Papa.unparse(data, {
      columns: state.columns.map((col) => col.label),
    });
    return new Blob([csv], { type: "text/csv;charset=utf-8;" });
  }

  function buildExcelBlob() {
    const data = toObjectArray();
    const worksheet = XLSX.utils.json_to_sheet(data);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Sheet1");
    const buffer = XLSX.write(workbook, { bookType: "xlsx", type: "array" });
    return new Blob([buffer], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
  }

  function toObjectArray() {
    return state.rows.map((row) => {
      const obj = {};
      state.columns.forEach((col) => {
        obj[col.label] = row.values[col.id] ?? "";
      });
      return obj;
    });
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    requestAnimationFrame(() => {
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    });
  }

  async function openWithFilePicker() {
    if (!window.showOpenFilePicker) {
      alert("이 브라우저에서는 지원하지 않는 기능입니다.");
      return;
    }
    try {
      const [handle] = await window.showOpenFilePicker({
        types: [
          {
            description: "CSV 또는 엑셀",
            accept: {
              "text/csv": [".csv"],
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                [".xlsx"],
            },
          },
        ],
      });
      const file = await handle.getFile();
      state.fileHandle = handle;
      state.fileFormat = getExtension(handle.name) === "xlsx" ? "xlsx" : "csv";
      state.currentFileName = handle.name;
      await loadFile(file);
      setStatus(`${handle.name} 불러오기 완료 (실험 기능)`);
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.error(error);
        alert("파일을 열 수 없습니다.");
      }
    }
  }

  async function saveThroughHandle() {
    if (!window.showSaveFilePicker && !state.fileHandle) {
      alert("이 브라우저에서는 지원하지 않는 기능입니다.");
      return;
    }
    try {
      if (!state.fileHandle) {
        state.fileHandle = await window.showSaveFilePicker({
          suggestedName: buildDownloadFileName(state.fileFormat),
          types: [
            {
              description: "CSV",
              accept: { "text/csv": [".csv"] },
            },
            {
              description: "엑셀 통합 문서",
              accept: {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                  [".xlsx"],
              },
            },
          ],
        });
        state.fileFormat =
          getExtension(state.fileHandle.name) === "xlsx" ? "xlsx" : "csv";
      }
      const format =
        getExtension(state.fileHandle.name) === "xlsx" ? "xlsx" : "csv";
      const blob = format === "xlsx" ? buildExcelBlob() : buildCsvBlob();
      const writable = await state.fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      setStatus(`${state.fileHandle.name} 저장 완료`);
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.error(error);
        alert("파일 저장에 실패했습니다.");
      }
    }
  }

  function onRenameColumnSelectChange() {
    refs.renameColumnValue.value = "";
  }

  function generateUniqueColumnId(label) {
    const base = slugify(label) || `col_${state.columns.length + 1}`;
    let candidate = base;
    let counter = 1;
    while (state.columns.some((col) => col.id === candidate)) {
      candidate = `${base}_${counter++}`;
    }
    return candidate;
  }

  function slugify(value) {
    return value
      .toLowerCase()
      .replace(/\s+/g, "_")
      .replace(/[^\w]/g, "")
      .replace(/^(\d)/, "_$1");
  }

  function makeId(prefix) {
    return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function getExtension(filename) {
    return filename.split(".").pop()?.toLowerCase() ?? "";
  }

  function setStatus(message) {
    refs.status.textContent = message;
  }
});
