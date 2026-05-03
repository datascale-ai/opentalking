import torch
from loguru import logger

from opentalking.core.model_config import get_model_config
from opentalking.engine.accelerator import patch_cuda_api_for_npu
from opentalking.engine.pipeline.flash_talk_pipeline import FlashTalkPipeline
from opentalking.engine.distributed.usp_device import get_device, get_parallel_degree

from opentalking.engine.configs import multitalk_14B
from opentalking.engine.audio.loudness import loudness_norm

infer_params = get_model_config("flashtalk")


def _bool_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


_AUDIO_LOUDNESS_NORM_ENABLED = _bool_enabled(infer_params.get("audio_loudness_norm", 1))


def _optional_config(name):
    value = infer_params.get(name)
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _resolve_t5_quant_options(t5_quant=None, t5_quant_dir=None, ckpt_dir=None):
    quant = t5_quant if t5_quant is not None else _optional_config("t5_quant")
    quant_dir = t5_quant_dir if t5_quant_dir is not None else _optional_config("t5_quant_dir")

    if quant is not None:
        quant = quant.lower()
        if quant not in {"int8", "fp8"}:
            raise ValueError(
                f"Unsupported FLASHTALK_T5_QUANT value: {quant!r}. Expected 'int8' or 'fp8'."
            )
        if quant_dir is None:
            quant_dir = ckpt_dir

    return quant, quant_dir


def _resolve_wan_quant_options(wan_quant=None, wan_quant_include=None, wan_quant_exclude=None):
    quant = wan_quant if wan_quant is not None else _optional_config("wan_quant")
    include = wan_quant_include if wan_quant_include is not None else _optional_config("wan_quant_include")
    exclude = wan_quant_exclude if wan_quant_exclude is not None else _optional_config("wan_quant_exclude")

    if quant is not None:
        quant = quant.lower()
        if quant not in {"int8", "fp8"}:
            raise ValueError(
                f"Unsupported FLASHTALK_WAN_QUANT value: {quant!r}. Expected 'int8' or 'fp8'."
            )

    return quant, include, exclude

# TODO: support more resolution
target_size = (infer_params['height'], infer_params['width'])


def get_pipeline(
    world_size,
    ckpt_dir,
    wav2vec_dir,
    cpu_offload=False,
    t5_quant=None,
    t5_quant_dir=None,
    wan_quant=None,
    wan_quant_include=None,
    wan_quant_exclude=None,
):
    patch_cuda_api_for_npu()
    cfg = multitalk_14B
    t5_quant, t5_quant_dir = _resolve_t5_quant_options(
        t5_quant=t5_quant,
        t5_quant_dir=t5_quant_dir,
        ckpt_dir=ckpt_dir,
    )
    wan_quant, wan_quant_include, wan_quant_exclude = _resolve_wan_quant_options(
        wan_quant=wan_quant,
        wan_quant_include=wan_quant_include,
        wan_quant_exclude=wan_quant_exclude,
    )

    ulysses_degree, ring_degree = get_parallel_degree(world_size, cfg.num_heads)
    device = get_device(ulysses_degree, ring_degree)
    logger.info(f"ulysses_degree: {ulysses_degree}, ring_degree: {ring_degree}, device: {device}")
    if t5_quant is not None:
        logger.warning(
            "T5 quantization flags are accepted for compatibility but not yet applied in opentalking.engine."
        )
    if wan_quant is not None:
        logger.warning(
            "Wan quantization flags are accepted for compatibility but not yet applied in opentalking.engine."
        )

    pipeline = FlashTalkPipeline(
        config=cfg,
        checkpoint_dir=ckpt_dir,
        wav2vec_dir=wav2vec_dir,
        device=device,
        use_usp=(world_size > 1),
        cpu_offload=cpu_offload,
        t5_quant=t5_quant,
        t5_quant_dir=t5_quant_dir,
        wan_quant=wan_quant,
        wan_quant_include=wan_quant_include,
        wan_quant_exclude=wan_quant_exclude,
    )

    return pipeline

def get_base_data(pipeline, input_prompt, cond_image, base_seed):
    pipeline.prepare_params(
        input_prompt=input_prompt, 
        cond_image=cond_image,
        target_size=target_size,
        frame_num=infer_params['frame_num'],
        motion_frames_num=infer_params['motion_frames_num'],
        sampling_steps=infer_params['sample_steps'],
        seed=base_seed,
        shift=infer_params['sample_shift'],
        color_correction_strength=infer_params['color_correction_strength'],
    )

def get_audio_embedding(pipeline, audio_array, audio_start_idx=-1, audio_end_idx=-1):
    if _AUDIO_LOUDNESS_NORM_ENABLED:
        audio_array = loudness_norm(audio_array, infer_params['sample_rate'])
    audio_embedding = pipeline.preprocess_audio(audio_array, sr=infer_params['sample_rate'], fps=infer_params['tgt_fps'])

    if audio_start_idx == -1 or audio_end_idx == -1:
        audio_start_idx = 0
        audio_end_idx = audio_embedding.shape[0]

    indices = (torch.arange(2 * 2 + 1) - 2) * 1

    center_indices = torch.arange(audio_start_idx, audio_end_idx, 1).unsqueeze(1) + indices.unsqueeze(0)
    center_indices = torch.clamp(center_indices, min=0, max=audio_end_idx-1)

    audio_embedding = audio_embedding[center_indices][None,...].contiguous()
    return audio_embedding

def run_pipeline(pipeline, audio_embedding):
    audio_embedding = audio_embedding.to(pipeline.device)
    sample = pipeline.generate(audio_embedding)
    sample_frames = (((sample+1)/2).permute(1,2,3,0).clip(0,1) * 255).contiguous()
    return sample_frames


def run_pipeline_deferred(pipeline, audio_embedding):
    """Run pipeline but defer motion-frame encode.

    Returns ``(video_frames, cond_frame)`` where ``video_frames`` is the
    same ``[T, H, W, C]`` uint8-range tensor as :func:`run_pipeline` and
    ``cond_frame`` must be passed to ``pipeline.finalize_motion_frames()``
    after the caller is done with the video data.
    """
    audio_embedding = audio_embedding.to(pipeline.device)
    sample, cond_frame = pipeline.generate_deferred_motion(audio_embedding)
    sample_frames = (((sample + 1) / 2).permute(1, 2, 3, 0).clip(0, 1) * 255).contiguous()
    return sample_frames, cond_frame


def run_pipeline_stream(pipeline, audio_embedding):
    """Streaming variant: yields (frame_uint8, is_motion) per decoded frame.

    ``frame_uint8`` has shape ``[n, H, W, C]`` (uint8, 0-255) where *n* is
    the number of pixel frames produced by one VAE time-step (typically 4,
    but 1 for the very first step).

    After the generator is fully consumed, ``pipeline.latent_motion_frames``
    is updated for the next chunk (same as :func:`run_pipeline`).
    """
    audio_embedding = audio_embedding.to(pipeline.device)
    for frame_pixels in pipeline.generate_stream(audio_embedding):
        # frame_pixels: [1, C, n, H, W], float, [-1, 1]
        # Convert to [n, H, W, C] uint8
        fp = frame_pixels[0]  # [C, n, H, W]
        fp = ((fp + 1) / 2).permute(1, 2, 3, 0).clamp_(0, 1) * 255
        yield fp.contiguous()
