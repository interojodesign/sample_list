# 샘플 리스트 관리자 (Streamlit)

Streamlit으로 작성된 간단한 리스트 관리 툴입니다. 동일 폴더의 CSV·엑셀 파일을 불러와 열/행을 수정하고 다시 저장할 수 있습니다.

## 필요한 패키지

```bash
pip install streamlit pandas openpyxl
```

## 실행 방법

```bash
streamlit run app.py
```

앱이 실행되면 브라우저가 자동으로 열립니다. 상단에서 파일을 불러오거나, 열·행 관리 섹션을 통해 스키마를 조정하세요. 편집한 내용은 다시 CSV/엑셀로 다운로드하거나 동일 폴더에 저장할 수 있습니다.
