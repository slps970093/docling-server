# Docling Serve - Document Embedding API

將 [Docling](https://github.com/docling-project/docling) 文件解析與 Embedding 整合為單一可執行檔，支援 Windows x64 與 Linux x64。服務只負責解析文件與轉向量，資料庫由外部應用程式管理。

## 功能

- `POST /rag/embed`：上傳文件，Docling 解析、切割 chunk、產生 embedding 向量，回傳 JSON
- `POST /rag/import`：提交預先切割的文本，產生 embedding 向量，回傳 JSON
- `GET /health`：健康檢查

## 環境需求

- Windows 10/11 x64 或 Linux x64
- 編譯時需要 Python 3.12（不支援 Python 3.14）
- 建議預留 12 GB 以上磁碟空間

執行檔不包含 Docling 與 Embedding 模型，首次執行時自動下載。

## 建置

Windows PowerShell：

```powershell
.\build.ps1 -Clean
```

Linux：

```bash
bash ./build.sh --clean
```

完成後執行檔位於：

- Windows：`dist\docling-serve.exe`
- Linux：`dist/docling-serve`

## 啟動服務

```powershell
.\dist\docling-serve.exe
```

預設監聽 `0.0.0.0:8000`，可透過環境變數調整：

```powershell
$env:RAG_HOST="0.0.0.0"
$env:RAG_PORT="8000"
```

服務無驗證機制，建議透過內網或反向代理使用。

## API 使用

### 上傳文件並轉向量

```powershell
curl.exe -X POST "http://localhost:8000/rag/embed" `
  -F "file=@C:\Docs\manual.pdf"
```

回傳 JSON：

```json
{
  "filename": "manual.pdf",
  "model": "BAAI/bge-small-zh-v1.5",
  "dimensions": 512,
  "items": [
    {
      "id": "uuid",
      "text": "文件內容 chunk",
      "embedding": [0.01, -0.02]
    }
  ]
}
```

### 提交預切割文本並轉向量

```powershell
curl.exe -X POST "http://localhost:8000/rag/import" `
  -H "Content-Type: application/json" `
  -d "{\"filename\":\"manual.pdf\",\"items\":[{\"text\":\"第一段文字\"},{\"text\":\"第二段文字\"}]}"
```

## RAG 架構

```text
外部應用程式
  -> Docling RAG Service (本專案)
  -> 回傳 chunks + vectors
  -> 外部應用程式寫入 PostgreSQL (pgvector)、Qdrant、Chroma 等向量資料庫
```

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `RAG_HOST` | `0.0.0.0` | 監聽位址 |
| `RAG_PORT` | `8000` | 監聽埠號 |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding 模型 |
| `RAG_CHUNK_SIZE` | `1200` | Chunk 字元大小 |
| `RAG_CHUNK_OVERLAP` | `150` | Chunk 重疊字元數 |
| `HF_HOME` | 預設 Hugging Face cache | 模型下載位置 |
| `DOCLING_SERVE_ARTIFACTS_PATH` | 預設 | Docling 模型快取位置 |

Windows 建議設定：

```powershell
$env:HF_HOME="D:\docling-models"
$env:DOCLING_SERVE_ARTIFACTS_PATH="D:\docling-models\docling"
$env:RAG_EMBEDDING_MODEL="BAAI/bge-m3"
```

## GitHub Actions

推送 tag 如 `v1.0.0`，或手動觸發 `Build binaries` workflow，GitHub Actions 會分別產出：

- `docling-serve-windows-x64`
- `docling-serve-linux-x64`

## License

MIT
