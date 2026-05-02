"""Shared Redis key names for API and worker."""

TASK_QUEUE = "opentalking:task_queue"
FLASHTALK_QUEUE_STATUS = "opentalking:flashtalk_queue_status"


def events_channel(session_id: str) -> str:
    return f"opentalking:events:{session_id}"


def offline_bundle_job_key(job_id: str) -> str:
    """FlashTalk 离线导出任务（上传 PCM → 推理结束 → 音视频落盘）。"""
    return f"opentalking:offline_bundle:{job_id}"


def uploaded_pcm_key(session_id: str, upload_id: str) -> str:
    return f"opentalking:uploaded_pcm:{session_id}:{upload_id}"
