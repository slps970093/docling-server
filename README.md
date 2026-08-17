# Docling Serve - Document Embedding API

將 [Docling](https://github.com/docling-project/docling) 文件解析與 Embedding 整合為單一可執行檔，支援 Windows x64 與 Linux x64。服務只負責解析文件與轉向量，資料庫由外部應用程式管理。

## 功能

- `POST /rag/embed`：上傳文件，同步解析、切割 chunk、產生 embedding 向量
- `POST /rag/embed/async`：非同步處理，支援上傳文件或 URL，完成後 Webhook 回呼
- `GET /rag/tasks/{task_id}`：查詢非同步任務狀態
- `POST /rag/import`：提交預先切割的文本，同步產生 embedding 向量
- `GET /health`：健康檢查
- 支援 CPU / GPU 切換
- 支援自訂模型、chunk 大小
- 模型自動下載並預設存放在執行檔旁 `huggingface/` 目錄

## 環境需求

- Windows 10/11 x64 或 Linux x64
- 編譯時需要 Python 3.12（不支援 Python 3.14）
- 建議預留 12 GB 以上磁碟空間
- GPU 模式需要 CUDA 相關驅動

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

預設監聽 `0.0.0.0:8000`。

### 命令列參數

```text
usage: docling-serve.exe [options]

  --host HOST              監聽位址（預設：0.0.0.0）
  --port PORT              監聽埠號（預設：8000）
  --device {auto,cpu,cuda} 計算裝置（預設：auto）
  --model MODEL            Embedding 模型（預設：BAAI/bge-small-zh-v1.5）
  --chunk-size SIZE        Chunk 字元大小（預設：1200）
  --chunk-overlap OVERLAP  Chunk 重疊字元數（預設：150）
```

### 使用範例

```powershell
# 預設啟動
.\dist\docling-serve.exe

# 指定埠號
.\dist\docling-serve.exe --port 9000

# 使用 GPU + 大模型
.\dist\docling-serve.exe --device cuda --model BAAI/bge-m3

# 完整參數
.\dist\docling-serve.exe `
  --host 0.0.0.0 `
  --port 9000 `
  --device cuda `
  --model BAAI/bge-m3 `
  --chunk-size 800 `
  --chunk-overlap 100
```

### 環境變數

所有參數也可透過環境變數設定，優先順序：args > 環境變數 > 預設值。

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `RAG_HOST` | `0.0.0.0` | 監聽位址 |
| `RAG_PORT` | `8000` | 監聽埠號 |
| `RAG_DEVICE` | `auto` | 計算裝置（auto / cpu / cuda） |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding 模型 |
| `RAG_CHUNK_SIZE` | `1200` | Chunk 字元大小 |
| `RAG_CHUNK_OVERLAP` | `150` | Chunk 重疊字元數 |
| `HF_HOME` | `<exe_dir>/huggingface` | 模型下載位置 |
| `DOCLING_SERVE_ARTIFACTS_PATH` | `<exe_dir>/docling_models` | Docling 模型快取位置 |

## API 使用

### 同步：上傳文件並轉向量

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

### 非同步：提交文件 + Webhook 回呼

上傳文件：

```powershell
curl.exe -X POST "http://localhost:8000/rag/embed/async" `
  -F "file=@C:\Docs\manual.pdf" `
  -F "webhook_url=https://your-app.com/callback" `
  -F "webhook_secret=optional-hmac-key"
```

透過 URL 下載：

```powershell
curl.exe -X POST "http://localhost:8000/rag/embed/async" `
  -F "url=https://example.com/document.pdf" `
  -F "webhook_url=https://your-app.com/callback"
```

立即回傳：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing"
}
```

### 查詢任務狀態

```powershell
curl.exe http://localhost:8000/rag/tasks/{task_id}
```

回傳：

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "filename": "manual.pdf",
  "created_at": 1700000000.0,
  "updated_at": 1700000005.0,
  "result": {
    "filename": "manual.pdf",
    "model": "BAAI/bge-small-zh-v1.5",
    "dimensions": 512,
    "items": [
      {"id": "uuid", "text": "chunk", "embedding": [0.01]}
    ]
  }
}
```

### Webhook 回呼格式

成功：

```json
{
  "task_id": "xxx",
  "status": "completed",
  "filename": "manual.pdf",
  "model": "BAAI/bge-small-zh-v1.5",
  "dimensions": 512,
  "items": [...]
}
```

失敗：

```json
{
  "task_id": "xxx",
  "status": "failed",
  "filename": "manual.pdf",
  "error": "No text was extracted"
}
```

HMAC 簽名（選用）：

```text
X-Webhook-Secret: sha256=xxx
```

Webhook 失敗會自動重試 3 次（間隔 5s、30s、60s），全部失敗後任務標記 `failed`，可透過查詢 API 取得結果。

### 提交預切割文本並轉向量

```powershell
curl.exe -X POST "http://localhost:8000/rag/import" `
  -H "Content-Type: application/json" `
  -d "{\"filename\":\"manual.pdf\",\"items\":[{\"text\":\"第一段文字\"},{\"text\":\"第二段文字\"}]}"
```

### 健康檢查

```powershell
curl.exe http://localhost:8000/health
```

## RAG 架構

```text
外部應用程式
  -> POST /rag/embed/async (上傳文件或 URL)
  <- 回傳 task_id
  -> 等待 Webhook 回呼 或 查詢 GET /rag/tasks/{task_id}
  -> 取得 chunks + vectors
  -> 外部應用程式寫入 PostgreSQL (pgvector)、Qdrant、Chroma 等向量資料庫
```

## 模型存放

模型下載後永久保留在：

- Windows：`dist\huggingface\hub\`
- Linux：`dist/huggingface/hub/`

後續啟動直接讀取快取，不需重新下載。可透過 `--model` 或 `RAG_EMBEDDING_MODEL` 切換模型。

## CPU / GPU 模式

| 模式 | 說明 |
|------|------|
| `auto`（預設） | 有 CUDA 用 GPU，沒有用 CPU |
| `cuda` | 強制使用 GPU |
| `cpu` | 強制使用 CPU |

啟動時會顯示：

```text
Torch version: 2.x.x, CUDA available: True
Loading embedding model: BAAI/bge-small-zh-v1.5 (device=cuda)
Embedding model loaded: BAAI/bge-small-zh-v1.5 on cuda
```

## 任務持久化

非同步任務狀態儲存在 SQLite：

```text
dist/tasks.db
```

服務重啟後任務仍可查詢。不需要額外安裝 Redis 或 RabbitMQ。

## GitHub Actions

推送 tag 如 `v1.0.0`，或手動觸發 `Build binaries` workflow，GitHub Actions 會分別產出：

- `docling-serve-windows-x64`
- `docling-serve-linux-x64`

## License

MIT
