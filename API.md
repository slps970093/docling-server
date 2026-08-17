# Docling RAG API 文件

Base URL：`http://localhost:8000`

---

## GET /health

健康檢查。

**回應**

```json
{"status": "ok", "service": "embedding"}
```

---

## POST /rag/embed

同步：上傳文件，Docling 解析、切割 chunk、產生 embedding 向量。

**請求**

```http
Content-Type: multipart/form-data
```

| 欄位 | 必填 | 說明 |
|------|------|------|
| file | ✅ | 文件（PDF / DOCX / PPTX / HTML / Markdown） |

**回應 200**

```json
{
  "filename": "manual.pdf",
  "model": "BAAI/bge-small-zh-v1.5",
  "dimensions": 512,
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "text": "文件內容 chunk",
      "embedding": [0.0123, -0.0456, 0.0789]
    }
  ]
}
```

**範例**

```bash
curl -X POST "http://localhost:8000/rag/embed" \
  -F "file=@manual.pdf"
```

---

## POST /rag/embed/async

非同步：上傳文件或提供 URL，立即回傳 task_id，背景處理完成後 Webhook 回呼。

**請求**

```http
Content-Type: multipart/form-data
```

| 欄位 | 必填 | 說明 |
|------|------|------|
| file | ⚠️ 二選一 | 上傳文件 |
| url | ⚠️ 二選一 | 文件 URL，服務自動下載 |
| webhook_url | ❌ | 完成後回呼的 URL |
| webhook_secret | ❌ | HMAC-SHA256 簽名用的 secret |

**回應 202**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing"
}
```

**範例：上傳文件**

```bash
curl -X POST "http://localhost:8000/rag/embed/async" \
  -F "file=@manual.pdf" \
  -F "webhook_url=https://your-app.com/callback" \
  -F "webhook_secret=my-secret"
```

**範例：URL 下載**

```bash
curl -X POST "http://localhost:8000/rag/embed/async" \
  -F "url=https://example.com/document.pdf" \
  -F "webhook_url=https://your-app.com/callback"
```

---

## GET /rag/tasks/{task_id}

查詢非同步任務狀態。

**路徑參數**

| 參數 | 說明 |
|------|------|
| task_id | 建立任務時回傳的 task_id |

**回應 200：處理中**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "filename": "manual.pdf",
  "created_at": 1700000000.0,
  "updated_at": 1700000000.0
}
```

**回應 200：完成**

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
      {
        "id": "uuid",
        "text": "文件內容",
        "embedding": [0.01, -0.02]
      }
    ]
  }
}
```

**回應 200：失敗**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "filename": "manual.pdf",
  "created_at": 1700000000.0,
  "updated_at": 1700000005.0,
  "error": "No text was extracted"
}
```

**回應 404**

```json
{"detail": "Task not found"}
```

**範例**

```bash
curl "http://localhost:8000/rag/tasks/550e8400-e29b-41d4-a716-446655440000"
```

---

## POST /rag/import

同步：提交預先切割的文本，產生 embedding 向量。

**請求**

```http
Content-Type: application/json
```

```json
{
  "filename": "manual.pdf",
  "items": [
    {"text": "第一段文字"},
    {"text": "第二段文字"}
  ]
}
```

| 欄位 | 必填 | 說明 |
|------|------|------|
| filename | ❌ | 文件名稱（預設 imported） |
| items | ✅ | 文本 chunk 列表 |
| items[].text | ✅ | chunk 內容 |

**回應 200**

```json
{
  "filename": "manual.pdf",
  "model": "BAAI/bge-small-zh-v1.5",
  "dimensions": 512,
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "text": "第一段文字",
      "embedding": [0.0123, -0.0456]
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "text": "第二段文字",
      "embedding": [0.0789, -0.0321]
    }
  ]
}
```

**範例**

```bash
curl -X POST "http://localhost:8000/rag/import" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "manual.pdf",
    "items": [
      {"text": "第一段文字"},
      {"text": "第二段文字"}
    ]
  }'
```

---

## Webhook 回呼格式

非同步任務完成後，服務會 POST 到 `webhook_url`。

### 成功

```json
{
  "task_id": "xxx",
  "status": "completed",
  "filename": "manual.pdf",
  "model": "BAAI/bge-small-zh-v1.5",
  "dimensions": 512,
  "items": [
    {"id": "uuid", "text": "chunk", "embedding": [0.01]}
  ]
}
```

### 失敗

```json
{
  "task_id": "xxx",
  "status": "failed",
  "filename": "manual.pdf",
  "error": "No text was extracted"
}
```

### HMAC 簽名

如果提供 `webhook_secret`，header 會包含：

```http
X-Webhook-Secret: sha256=xxxx
```

驗證方式：

```python
import hmac, hashlib

def verify_webhook(payload_bytes: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### 重試機制

Webhook 失敗會自動重試 3 次：

| 次數 | 間隔 |
|------|------|
| 1 | 5 秒 |
| 2 | 30 秒 |
| 3 | 60 秒 |

全部失敗後任務標記 `failed`，可透過 `GET /rag/tasks/{task_id}` 查詢。

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| RAG_HOST | 0.0.0.0 | 監聽位址 |
| RAG_PORT | 8000 | 監聽埠號 |
| RAG_DEVICE | auto | 計算裝置（auto / cpu / cuda） |
| RAG_EMBEDDING_MODEL | BAAI/bge-small-zh-v1.5 | Embedding 模型 |
| RAG_CHUNK_SIZE | 1200 | Chunk 字元大小 |
| RAG_CHUNK_OVERLAP | 150 | Chunk 重疊字元數 |
| HF_HOME | exe_dir/huggingface | 模型下載位置 |
| DOCLING_SERVE_ARTIFACTS_PATH | exe_dir/docling_models | Docling 模型快取 |

---

## 任務狀態流轉

```text
processing -> completed (成功)
processing -> failed (失敗)
```

---

## 資料流

### 同步流程

```text
POST /rag/embed
  -> 解析文件
  -> 切割 chunks
  -> 產生 embedding
  <- 回傳 items
```

### 非同步流程

```text
POST /rag/embed/async
  <- 回傳 task_id (202)
  -> 背景 thread 執行
  -> 完成後 Webhook 回呼
  -> 或 GET /rag/tasks/{task_id} 查詢
```

### URL 下載流程

```text
POST /rag/embed/async (url=...)
  -> 從 URL 下載文件
  -> 解析文件
  -> 切割 chunks
  -> 產生 embedding
  -> Webhook 回呼
```
