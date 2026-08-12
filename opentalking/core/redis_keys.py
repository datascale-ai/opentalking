"""Shared Redis key names for API and worker."""

TASK_QUEUE = "opentalking:task_queue"
FLASHTALK_QUEUE_STATUS = "opentalking:flashtalk_queue_status"


def command_receipt_key(session_id: str, command_id: str) -> str:
    return f"opentalking:command:{session_id}:{command_id}"


def events_channel(session_id: str) -> str:
    return f"opentalking:events:{session_id}"


def offline_bundle_job_key(job_id: str) -> str:
    """FlashTalk 离线导出任务（上传 PCM → 推理结束 → 音视频落盘）。"""
    return f"opentalking:offline_bundle:{job_id}"


def uploaded_pcm_key(session_id: str, upload_id: str) -> str:
    return f"opentalking:uploaded_pcm:{session_id}:{upload_id}"


def streaming_output_index_key(session_id: str) -> str:
    """Short-lived streaming output snapshot index for one Session."""
    return f"opentalking:streaming:index:{session_id}"


def streaming_output_key(session_id: str, output_id: str) -> str:
    """Secret-free output snapshot key."""
    return f"opentalking:streaming:output:{session_id}:{output_id}"


def streaming_receipt_key(session_id: str, action: str, idempotency_key: str) -> str:
    """Hashed streaming command receipt key; raw caller keys never enter Redis keys."""
    import hashlib

    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"opentalking:streaming:receipt:{session_id}:{action}:{digest}"
