# Avatars

Endpoints for browsing avatar bundles, retrieving manifests and preview images, and
creating custom avatars from a portrait image.

The avatar bundle format is documented separately in
[Avatar Format](../user-guide/avatar-format.md).

## `GET /avatars`

Returns the list of avatar bundles present in `OPENTALKING_AVATARS_DIR`. Hidden
avatars (those with `metadata.hidden=true`) are omitted.

**Response — `200 OK`**

Body type: `list[AvatarSummary]`.

### `AvatarSummary`

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Globally unique avatar identifier. |
| `name` | string \| null | Display name. Defaults to `id`. |
| `model_type` | string | One of `wav2lip`, `musetalk`, `quicktalk`, `flashtalk`, `flashhead`, `mock`. |
| `width` | integer | Output video width in pixels. |
| `height` | integer | Output video height in pixels. |
| `is_custom` | boolean | `true` when the avatar was created via `POST /avatars/custom` and may be deleted. |

```bash title="curl"
curl -s http://localhost:8000/avatars | jq
```

```json title="response"
[
  {
    "id": "demo-avatar",
    "name": "Demo",
    "model_type": "mock",
    "width": 512,
    "height": 512,
    "is_custom": false
  },
  {
    "id": "custom-alice-20260513-153012-001",
    "name": "Alice",
    "model_type": "wav2lip",
    "width": 1024,
    "height": 1024,
    "is_custom": true
  }
]
```

## `GET /avatars/{avatar_id}`

Returns the complete `manifest.json` for the requested avatar, including the
`metadata` block.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `avatar_id` | string | Avatar identifier from `GET /avatars`. |

**Response — `200 OK`**

The complete manifest object. The schema is documented in
[Avatar Format → manifest.json schema](../user-guide/avatar-format.md#manifestjson-schema).

```bash title="curl"
curl -s http://localhost:8000/avatars/demo-avatar | jq
```

```json title="response"
{
  "id": "demo-avatar",
  "name": "Demo",
  "model_type": "mock",
  "fps": 25,
  "sample_rate": 16000,
  "width": 512,
  "height": 512,
  "version": "1.0",
  "metadata": {}
}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | The avatar identifier was not found. |

## `GET /avatars/{avatar_id}/preview`

Returns the `preview.png` file for the avatar. The response body is binary image
content.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `avatar_id` | string | Avatar identifier. |

**Response — `200 OK`**

Content-Type: `image/png`. Body is the raw PNG file.

**Error responses**

| Code | Condition |
|------|-----------|
| `404` | The avatar or its `preview.png` file is missing. |

## `POST /avatars/custom`

Creates a new avatar bundle by combining the manifest of a base avatar with a
user-supplied portrait image. The newly created avatar is tagged
`metadata.custom_avatar=true`, which makes it eligible for deletion via
`DELETE /avatars/{avatar_id}`.

**Request body — `multipart/form-data`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Display name for the new avatar. |
| `base_avatar_id` | string | Yes | Identifier of an existing avatar to use as manifest template. The base avatar must have `model_type=wav2lip`. |
| `image` | file | Yes | Portrait image, maximum 10 MB. Acceptable formats: JPEG, PNG, WebP. |

**Behavior**

1. The base avatar's `manifest.json` is loaded.
2. A new avatar identifier is generated in the form `custom-<slug>-<timestamp>`.
3. The uploaded image is converted to RGB and saved as `frames/frame_00000.png` in the new bundle directory.
4. MediaPipe mouth detection is attempted; on success the result is written to `metadata.animation`. On failure the upload still succeeds but `animation` is omitted.
5. The new manifest's `id` and `name` are overwritten, and `metadata.custom_avatar=true` and `metadata.base_avatar_id=<base>` are recorded.

**Response — `200 OK`**

Body type: `AvatarSummary` of the newly created avatar.

```bash title="curl"
curl -X POST http://localhost:8000/avatars/custom \
  -F name="Alice" \
  -F base_avatar_id=demo-wav2lip \
  -F image=@portrait.jpg
```

```json title="response"
{
  "id": "custom-alice-20260513-153012-001",
  "name": "Alice",
  "model_type": "wav2lip",
  "width": 1024,
  "height": 1024,
  "is_custom": true
}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `400` | The uploaded image is empty, invalid, or exceeds 10 MB. |
| `404` | The base avatar identifier was not found. |
| `413` | The uploaded image exceeds 10 MB. |

## `DELETE /avatars/{avatar_id}`

Removes a custom avatar bundle from disk. Only avatars created via
`POST /avatars/custom` may be deleted; deletion of built-in or hidden avatars is
rejected.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `avatar_id` | string | Avatar identifier. Must satisfy `is_custom=true`. |

**Response — `200 OK`**

```json
{"deleted": true}
```

**Error responses**

| Code | Condition |
|------|-----------|
| `403` | The avatar is not marked custom and cannot be deleted. |
| `404` | The avatar identifier was not found. |

## Source files

- `apps/api/routes/avatars.py` — endpoint implementations.
- `apps/api/schemas/avatar.py` — `AvatarSummary` response model.
- `opentalking/avatar/loader.py` — `load_avatar_bundle()`.
- `opentalking/avatar/validator.py` — `list_avatar_dirs()`.
- `opentalking/avatar/mouth_metadata.py` — MediaPipe mouth detection.
