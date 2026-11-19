# drive.upload

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.file`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | No | Local file path to stream from disk (resumable). Mutually exclusive with content_b64. (default: None) |
| `content_b64` | string | No | Base64-encoded inline content. Mutually exclusive with path. (default: None) |
| `filename` | string | No | Display/MIME basename; defaults to os.path.basename(path) when path is given. (default: None) |
| `title` | string | No | Title (default: None) |
| `mime_type` | string | No | Mime Type (default: None) |
| `folder_id` | string | No | Folder Id (default: None) |
| `folder_name` | string | No | Folder Name (default: 'google-kit-uploads') |
| `share` | string | No | Share (default: 'private') |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Id |
| `url` | string | Url |
| `name` | string | Name |
| `mime_type` | string | Mime Type |
| `shared` | boolean | Shared |

## Performance / Quota

- api: Drive v3
- method: files.create (resumable) [+ permissions.create when share=anyone_reader]
- quota: 500 req/day

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit drive upload --path /tmp/clip.mp4 --folder-id <folder-id>`

**MCP tool:** `drive_upload`
```json
{
  "path": "/tmp/clip.mp4",
  "folder_id": "<folder-id>"
}
```
> **Note:** Provide exactly one of 'path' (streamed from disk via resumable MediaFileUpload — any size/binary) or 'content_b64' (inline base64, small files only). 'filename' defaults to the path basename; MIME is guessed from the extension when 'mime_type' is omitted. Sharing is PRIVATE by default (no permissions call); pass share='anyone_reader' to explicitly grant type=anyone, role=reader. Output data: {id, url, name, mime_type, shared}.

