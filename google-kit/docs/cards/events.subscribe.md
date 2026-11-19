# events.subscribe

**Posture:** write  **Scopes:** `https://www.googleapis.com/auth/drive.readonly`

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_resource` | string | Yes | Full resource name of the Drive target, e.g. a file '//drive.googleapis.com/files/<id>' or shared drive '//drive.googleapis.com/drives/<id>'. |
| `event_types` | array | Yes | List of Drive event type strings (CloudEvents format google.workspace.drive.RESOURCE.v3.ACTION), e.g. ['google.workspace.drive.file.v3.contentChanged']. Valid file actions: created, moved, contentChanged, deleted, trashed, untrashed, renamed. The event must match the target: a single-file target supports file-scoped events (e.g. contentChanged); container events (created/moved) require a folder or shared-drive target. |
| `pubsub_topic` | string | Yes | Fully-qualified Pub/Sub topic name, e.g. 'projects/<project>/topics/<topic>'. |
| `payload_options` | object | No | Optional payloadOptions object to control event payload shape. (default: None) |

## Output (`data` fields)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Name |
| `done` | boolean | Done |

## Performance / Quota

- api: Workspace Events v1
- method: subscriptions.create
- quota: varies

## Errors

| Class | When |
|-------|------|
| `Auth` | Invalid or expired credentials |
| `QuotaRateLimit` | Quota exceeded; retried automatically |
| `Transient` | 5xx server error; retried automatically (max 4 attempts) |
| `NotFound` | Resource not found |
## Example

**CLI:** `google-kit events subscribe`

**MCP tool:** `events_subscribe`
```json
{
  "target_resource": "//drive.googleapis.com/files/<file-id>",
  "event_types": [
    "google.workspace.drive.file.v3.contentChanged"
  ],
  "pubsub_topic": "projects/<project>/topics/<topic>"
}
```
> **Note:** Requires an operator-provisioned Cloud Pub/Sub topic; §7 covers Drive event targets only. A single-file target pairs with file-scoped events (e.g. contentChanged); container events (created/moved) need a folder or shared-drive target.

