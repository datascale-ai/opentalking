import os
from einops import rearrange

import torch
import torch.nn as nn

from xfuser.core.distributed import get_sp_group

from einops import rearrange, repeat
from functools import lru_cache
import imageio
from tqdm import tqdm
import numpy as np
import subprocess
import torchvision
import binascii
import os.path as osp
from skimage import color

import math
from PIL import Image
import torchvision.transforms as transforms
import torch.nn as nn
import pyloudnorm as pyln

VID_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv")
ASPECT_RATIO_627 = {
     '0.26': ([320, 1216], 1), '0.38': ([384, 1024], 1), '0.50': ([448, 896], 1), '0.67': ([512, 768], 1), 
     '0.82': ([576, 704], 1),  '1.00': ([640, 640], 1),  '1.22': ([704, 576], 1), '1.50': ([768, 512], 1), 
     '1.86': ([832, 448], 1),  '2.00': ([896, 448], 1),  '2.50': ([960, 384], 1), '2.83': ([1088, 384], 1), 
     '3.60': ([1152, 320], 1), '3.80': ([1216, 320], 1), '4.00': ([1280, 320], 1)}


ASPECT_RATIO_960 = {
     '0.22': ([448, 2048], 1), '0.29': ([512, 1792], 1), '0.36': ([576, 1600], 1), '0.45': ([640, 1408], 1), 
     '0.55': ([704, 1280], 1), '0.63': ([768, 1216], 1), '0.76': ([832, 1088], 1), '0.88': ([896, 1024], 1), 
     '1.00': ([960, 960], 1), '1.14': ([1024, 896], 1), '1.31': ([1088, 832], 1), '1.50': ([1152, 768], 1), 
     '1.58': ([1216, 768], 1), '1.82': ([1280, 704], 1), '1.91': ([1344, 704], 1), '2.20': ([1408, 640], 1), 
     '2.30': ([1472, 640], 1), '2.67': ([1536, 576], 1), '2.89': ([1664, 576], 1), '3.62': ([1856, 512], 1), 
     '3.75': ([1920, 512], 1)}



def torch_gc():
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()

def split_token_counts_and_frame_ids(T, token_frame, world_size, rank):
    S = T * token_frame

    # compute split sizes per rank
    base = S // world_size
    rem = S % world_size
    split_sizes = torch.full((world_size,), base, dtype=torch.long)
    split_sizes[:rem] += 1

    start = split_sizes[:rank].sum()
    end = start + split_sizes[rank]

    # vectorized mapping: global index -> frame id
    idx = torch.arange(start, end, dtype=torch.long)
    frame_ids = idx // token_frame

    # unique counts
    unique_frames, counts = torch.unique(frame_ids, return_counts=True)

    # return as Python list (optional)
    return counts.tolist(), unique_frames.tolist()

def normalize_and_scale(column, source_range, target_range, epsilon=1e-8):

    source_min, source_max = source_range
    new_min, new_max = target_range
 
    normalized = (column - source_min) / (source_max - source_min + epsilon)
    scaled = normalized * (new_max - new_min) + new_min
    return scaled


@torch.compile
def calculate_x_ref_attn_map(visual_q, ref_k, ref_target_masks, mode='mean', attn_bias=None):
    
    ref_k = ref_k.to(visual_q.dtype).to(visual_q.device)
    scale = 1.0 / visual_q.shape[-1] ** 0.5
    visual_q = visual_q * scale
    visual_q = visual_q.transpose(1, 2)
    ref_k = ref_k.transpose(1, 2)
    attn = visual_q @ ref_k.transpose(-2, -1)

    if attn_bias is not None:
        attn = attn + attn_bias

    x_ref_attn_map_source = attn.softmax(-1) # B, H, x_seqlens, ref_seqlens


    x_ref_attn_maps = []
    ref_target_masks = ref_target_masks.to(visual_q.dtype)
    x_ref_attn_map_source = x_ref_attn_map_source.to(visual_q.dtype)

    for class_idx, ref_target_mask in enumerate(ref_target_masks):
        torch_gc()
        ref_target_mask = ref_target_mask[None, None, None, ...]  # 1 1 1 hw
        x_ref_attnmap = x_ref_attn_map_source * ref_target_mask
        x_ref_attnmap = x_ref_attnmap.sum(-1) / ref_target_mask.sum() # B, H, x_seqlens, ref_seqlens --> B, H, x_seqlens
        x_ref_attnmap = x_ref_attnmap.permute(0, 2, 1) # B, x_seqlens, H
       
        if mode == 'mean':
            x_ref_attnmap = x_ref_attnmap.mean(-1) # B, x_seqlens
        elif mode == 'max':
            x_ref_attnmap = x_ref_attnmap.max(-1) # B, x_seqlens
        
        x_ref_attn_maps.append(x_ref_attnmap)
    
    del attn
    del x_ref_attn_map_source
    torch_gc()

    return torch.concat(x_ref_attn_maps, dim=0)


def get_attn_map_with_target(visual_q, ref_k, shape, ref_target_masks=None, split_num=2, enable_sp=False):
    """Args:
        query (torch.tensor): B M H K
        key (torch.tensor): B M H K
        shape (tuple): (N_t, N_h, N_w)
        ref_target_masks: [B, N_h * N_w]
    """

    N_t, N_h, N_w = shape
    if enable_sp:
        ref_k = get_sp_group().all_gather(ref_k, dim=1)
    
    x_seqlens = N_h * N_w
    ref_k     = ref_k[:, :x_seqlens]
    _, seq_lens, heads, _ = visual_q.shape
    class_num, _ = ref_target_masks.shape
    x_ref_attn_maps = torch.zeros(class_num, seq_lens).to(visual_q.device).to(visual_q.dtype)

    split_chunk = heads // split_num
    
    for i in range(split_num):
        x_ref_attn_maps_perhead = calculate_x_ref_attn_map(visual_q[:, :, i*split_chunk:(i+1)*split_chunk, :], ref_k[:, :, i*split_chunk:(i+1)*split_chunk, :], ref_target_masks)
        x_ref_attn_maps += x_ref_attn_maps_perhead
    
    return x_ref_attn_maps / split_num


def rotate_half(x):
    x = rearrange(x, "... (d r) -> ... d r", r=2)
    x1, x2 = x.unbind(dim=-1)
    x = torch.stack((-x2, x1), dim=-1)
    return rearrange(x, "... d r -> ... (d r)")


class RotaryPositionalEmbedding1D(nn.Module):

    def __init__(self,
                 head_dim,
                 ):
        super().__init__()
        self.head_dim = head_dim
        self.base = 10000


    @lru_cache(maxsize=32)
    def precompute_freqs_cis_1d(self, pos_indices):

        freqs = 1.0 / (self.base ** (torch.arange(0, self.head_dim, 2)[: (self.head_dim // 2)].float() / self.head_dim))
        freqs = freqs.to(pos_indices.device)
        freqs = torch.einsum("..., f -> ... f", pos_indices.float(), freqs)
        freqs = repeat(freqs, "... n -> ... (n r)", r=2)
        return freqs

    def forward(self, x, pos_indices):
        """1D RoPE.

        Args:
            query (torch.tensor): [B, head, seq, head_dim]
            pos_indices (torch.tensor): [seq,]
        Returns:
            query with the same shape as input.
        """
        freqs_cis = self.precompute_freqs_cis_1d(pos_indices)

        x_ = x.float()

        freqs_cis = freqs_cis.float().to(x.device)
        cos, sin = freqs_cis.cos(), freqs_cis.sin()
        cos, sin = rearrange(cos, 'n d -> 1 1 n d'), rearrange(sin, 'n d -> 1 1 n d')
        x_ = (x_ * cos) + (rotate_half(x_) * sin)

        return x_.type_as(x)
    


def rand_name(length=8, suffix=''):
    name = binascii.b2a_hex(os.urandom(length)).decode('utf-8')
    if suffix:
        if not suffix.startswith('.'):
            suffix = '.' + suffix
        name += suffix
    return name

def cache_video(tensor,
                save_file=None,
                fps=30,
                suffix='.mp4',
                nrow=8,
                normalize=True,
                value_range=(-1, 1),
                retry=5):
    
    # cache file
    cache_file = osp.join('/tmp', rand_name(
        suffix=suffix)) if save_file is None else save_file

    # save to cache
    error = None
    for _ in range(retry):
       
        # preprocess
        tensor = tensor.clamp(min(value_range), max(value_range))
        tensor = torch.stack([
                torchvision.utils.make_grid(
                    u, nrow=nrow, normalize=normalize, value_range=value_range)
                for u in tensor.unbind(2)
            ],
                                 dim=1).permute(1, 2, 3, 0)
        tensor = (tensor * 255).type(torch.uint8).cpu()

        # write video
        writer = imageio.get_writer(cache_file, fps=fps, codec='libx264', quality=10, ffmpeg_params=["-crf", "10"])
        for frame in tensor.numpy():
            writer.append_data(frame)
        writer.close()
        return cache_file

def save_video_ffmpeg(gen_video_samples, save_path, vocal_audio_list, fps=25, quality=5, high_quality_save=False, drift=0):
    
    def save_video(frames, save_path, fps, quality=9, ffmpeg_params=None):
        writer = imageio.get_writer(
            save_path, fps=fps, quality=quality, ffmpeg_params=ffmpeg_params
        )
        for frame in tqdm(frames, desc="Saving video"):
            frame = np.array(frame)
            writer.append_data(frame)
        writer.close()
    save_path_tmp = save_path + "-temp.mp4"

    if high_quality_save:
        cache_video(
                    tensor=gen_video_samples.unsqueeze(0),
                    save_file=save_path_tmp,
                    fps=fps,
                    nrow=1,
                    normalize=True,
                    value_range=(-1, 1)
                    )
    else:
        video_audio = (gen_video_samples+1)/2 # C T H W
        video_audio = video_audio.permute(1, 2, 3, 0).cpu().numpy()
        video_audio = np.clip(video_audio * 255, 0, 255).astype(np.uint8)  # to [0, 255]
        save_video(video_audio, save_path_tmp, fps=fps, quality=quality)


    # crop audio according to video length
    _, T, _, _ = gen_video_samples.shape
    duration = T / fps
    save_path_crop_audio = save_path + "-cropaudio.wav"
    final_command = [
        "ffmpeg",
        "-ss", f"{drift}",
        "-i",
        vocal_audio_list[0],
        "-t",
        f'{duration + drift}',
        save_path_crop_audio,
    ]
    subprocess.run(final_command, check=True)

    save_path = save_path + ".mp4"
    if high_quality_save:
        final_command = [
            "ffmpeg",
            "-y",
            "-i", save_path_tmp,
            "-i", save_path_crop_audio,
            "-c:v", "libx264",
            "-crf", "0",
            "-preset", "veryslow",
            "-c:a", "aac", 
            "-shortest",
            save_path,
        ]
        subprocess.run(final_command, check=True)
        os.remove(save_path_tmp)
        os.remove(save_path_crop_audio)
    else:
        final_command = [
            "ffmpeg",
            "-y",
            "-i",
            save_path_tmp,
            "-i",
            save_path_crop_audio,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            save_path,
        ]
        subprocess.run(final_command, check=True)
        os.remove(save_path_tmp)
        os.remove(save_path_crop_audio)


class MomentumBuffer:
    def __init__(self, momentum: float): 
        self.momentum = momentum 
        self.running_average = 0 
    
    def update(self, update_value: torch.Tensor): 
        new_average = self.momentum * self.running_average 
        self.running_average = update_value + new_average
    


def project( 
        v0: torch.Tensor, # [B, C, T, H, W] 
        v1: torch.Tensor, # [B, C, T, H, W] 
        ): 
    dtype = v0.dtype 
    v0, v1 = v0.double(), v1.double() 
    v1 = torch.nn.functional.normalize(v1, dim=[-1, -2, -3, -4]) 
    v0_parallel = (v0 * v1).sum(dim=[-1, -2, -3, -4], keepdim=True) * v1 
    v0_orthogonal = v0 - v0_parallel
    return v0_parallel.to(dtype), v0_orthogonal.to(dtype)


def adaptive_projected_guidance( 
          diff: torch.Tensor, # [B, C, T, H, W] 
          pred_cond: torch.Tensor, # [B, C, T, H, W] 
          momentum_buffer: MomentumBuffer = None, 
          eta: float = 0.0,
          norm_threshold: float = 55,
          ): 
    if momentum_buffer is not None: 
        momentum_buffer.update(diff) 
        diff = momentum_buffer.running_average
    if norm_threshold > 0: 
        ones = torch.ones_like(diff) 
        diff_norm = diff.norm(p=2, dim=[-1, -2, -3, -4], keepdim=True) 
        print(f"diff_norm: {diff_norm}")
        scale_factor = torch.minimum(ones, norm_threshold / diff_norm) 
        diff = diff * scale_factor 
    diff_parallel, diff_orthogonal = project(diff, pred_cond) 
    normalized_update = diff_orthogonal + eta * diff_parallel
    return normalized_update

def match_and_blend_colors(source_chunk: torch.Tensor, reference_image: torch.Tensor, strength: float) -> torch.Tensor:
    """
    Matches the color of a source video chunk to a reference image and blends with the original.

    Args:
        source_chunk (torch.Tensor): The video chunk to be color-corrected (B, C, T, H, W) in range [-1, 1].
                                     Assumes B=1 (batch size of 1).
        reference_image (torch.Tensor): The reference image (B, C, 1, H, W) in range [-1, 1].
                                        Assumes B=1 and T=1 (single reference frame).
        strength (float): The strength of the color correction (0.0 to 1.0).
                          0.0 means no correction, 1.0 means full correction.

    Returns:
        torch.Tensor: The color-corrected and blended video chunk.
    """
    # print(f"[match_and_blend_colors] Input source_chunk shape: {source_chunk.shape}, reference_image shape: {reference_image.shape}, strength: {strength}")

    if strength == 0.0:
        # print(f"[match_and_blend_colors] Strength is 0, returning original source_chunk.")
        return source_chunk

    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"Strength must be between 0.0 and 1.0, got {strength}")

    device = source_chunk.device
    dtype = source_chunk.dtype

    # Squeeze batch dimension, permute to T, H, W, C for skimage
    # Source: (1, C, T, H, W) -> (T, H, W, C)
    source_np = source_chunk.squeeze(0).permute(1, 2, 3, 0).cpu().numpy()
    # Reference: (1, C, 1, H, W) -> (H, W, C)
    ref_np = reference_image.squeeze(0).squeeze(1).permute(1, 2, 0).cpu().numpy() # Squeeze T dimension as well

    # Normalize from [-1, 1] to [0, 1] for skimage
    source_np_01 = (source_np + 1.0) / 2.0
    ref_np_01 = (ref_np + 1.0) / 2.0

    # Clip to ensure values are strictly in [0, 1] after potential float precision issues
    source_np_01 = np.clip(source_np_01, 0.0, 1.0)
    ref_np_01 = np.clip(ref_np_01, 0.0, 1.0)

    # Convert reference to Lab
    try:
        ref_lab = color.rgb2lab(ref_np_01)
    except ValueError as e:
        # Handle potential errors if image data is not valid for conversion
        print(f"Warning: Could not convert reference image to Lab: {e}. Skipping color correction for this chunk.")
        return source_chunk


    corrected_frames_np_01 = []
    for i in range(source_np_01.shape[0]): # Iterate over time (T)
        source_frame_rgb_01 = source_np_01[i]
        
        try:
            source_lab = color.rgb2lab(source_frame_rgb_01)
        except ValueError as e:
            print(f"Warning: Could not convert source frame {i} to Lab: {e}. Using original frame.")
            corrected_frames_np_01.append(source_frame_rgb_01)
            continue

        corrected_lab_frame = source_lab.copy()

        # Perform color transfer for L, a, b channels
        for j in range(3): # L, a, b
            mean_src, std_src = source_lab[:, :, j].mean(), source_lab[:, :, j].std()
            mean_ref, std_ref = ref_lab[:, :, j].mean(), ref_lab[:, :, j].std()

            # Avoid division by zero if std_src is 0
            if std_src == 0:
                # If source channel has no variation, keep it as is, but shift by reference mean
                # This case is debatable, could also just copy source or target mean.
                # Shifting by target mean helps if source is flat but target isn't.
                corrected_lab_frame[:, :, j] = mean_ref 
            else:
                corrected_lab_frame[:, :, j] = (corrected_lab_frame[:, :, j] - mean_src) * (std_ref / std_src) + mean_ref
        
        try:
            fully_corrected_frame_rgb_01 = color.lab2rgb(corrected_lab_frame)
        except ValueError as e:
            print(f"Warning: Could not convert corrected frame {i} back to RGB: {e}. Using original frame.")
            corrected_frames_np_01.append(source_frame_rgb_01)
            continue
            
        # Clip again after lab2rgb as it can go slightly out of [0,1]
        fully_corrected_frame_rgb_01 = np.clip(fully_corrected_frame_rgb_01, 0.0, 1.0)

        # Blend with original source frame (in [0,1] RGB)
        blended_frame_rgb_01 = (1 - strength) * source_frame_rgb_01 + strength * fully_corrected_frame_rgb_01
        corrected_frames_np_01.append(blended_frame_rgb_01)

    corrected_chunk_np_01 = np.stack(corrected_frames_np_01, axis=0)

    # Convert back to [-1, 1]
    corrected_chunk_np_minus1_1 = (corrected_chunk_np_01 * 2.0) - 1.0

    # Permute back to (C, T, H, W), add batch dim, and convert to original torch.Tensor type and device
    # (T, H, W, C) -> (C, T, H, W)
    corrected_chunk_tensor = torch.from_numpy(corrected_chunk_np_minus1_1).permute(3, 0, 1, 2).unsqueeze(0)
    corrected_chunk_tensor = corrected_chunk_tensor.contiguous() # Ensure contiguous memory layout
    output_tensor = corrected_chunk_tensor.to(device=device, dtype=dtype)
    # print(f"[match_and_blend_colors] Output tensor shape: {output_tensor.shape}")
    return output_tensor

def rgb_to_lab_torch(rgb: torch.Tensor) -> torch.Tensor:
    """
    PyTorch GPU版本：RGB转Lab颜色空间（输入范围[0,1]，张量形状任意，最后一维为通道数）
    参考CIE 1931标准转换公式
    """
    # 转换为线性RGB（sRGB伽马校正逆过程）
    linear_rgb = torch.where(
        rgb > 0.04045,
        ((rgb + 0.055) / 1.055) ** 2.4,
        rgb / 12.92
    )
    
    # 线性RGB转XYZ（使用sRGB标准白点D65）
    xyz_from_rgb = torch.tensor([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041]
    ], dtype=rgb.dtype, device=rgb.device)
    
    # 维度适配：确保输入为(B, ..., C)，矩阵乘法后保持空间维度
    shape = linear_rgb.shape
    linear_rgb_flat = linear_rgb.reshape(-1, 3)  # (N, 3)，N=B*T*H*W
    xyz_flat = linear_rgb_flat @ xyz_from_rgb.T  # (N, 3)
    xyz = xyz_flat.reshape(shape)  # 恢复原形状
    
    # XYZ转Lab（使用D65白点参数）
    xyz_ref = torch.tensor([0.95047, 1.0, 1.08883], dtype=rgb.dtype, device=rgb.device)
    xyz_normalized = xyz / xyz_ref[None, None, None, None, :]  # 广播适配(B, C, T, H, W)
    
    # 应用Lab转换公式
    epsilon = 0.008856
    kappa = 903.3
    xyz_normalized = torch.clamp(xyz_normalized, 1e-8, 1.0)  # 避免log(0)
    
    f_xyz = torch.where(
        xyz_normalized > epsilon,
        xyz_normalized ** (1/3),
        (kappa * xyz_normalized + 16) / 116
    )
    
    L = 116 * f_xyz[..., 1] - 16  # Y通道对应亮度
    a = 500 * (f_xyz[..., 0] - f_xyz[..., 1])  # X-Y对应红绿
    b = 200 * (f_xyz[..., 1] - f_xyz[..., 2])  # Y-Z对应蓝黄
    
    lab = torch.stack([L, a, b], dim=-1)  # 最后一维拼接为Lab通道
    return lab

def lab_to_rgb_torch(lab: torch.Tensor) -> torch.Tensor:
    """
    PyTorch GPU版本：Lab转RGB颜色空间（输出范围[0,1]，张量形状任意，最后一维为通道数）
    """
    # Lab分离通道
    L = lab[..., 0]
    a = lab[..., 1]
    b = lab[..., 2]
    
    # Lab转XYZ
    f_y = (L + 16) / 116
    f_x = (a / 500) + f_y
    f_z = f_y - (b / 200)
    
    epsilon = 0.008856
    kappa = 903.3
    
    x = torch.where(f_x ** 3 > epsilon, f_x ** 3, (116 * f_x - 16) / kappa)
    y = torch.where(L > kappa * epsilon, ((L + 16) / 116) ** 3, L / kappa)
    z = torch.where(f_z ** 3 > epsilon, f_z ** 3, (116 * f_z - 16) / kappa)
    
    # 乘以D65白点参数
    xyz_ref = torch.tensor([0.95047, 1.0, 1.08883], dtype=lab.dtype, device=lab.device)
    xyz = torch.stack([x, y, z], dim=-1) * xyz_ref[None, None, None, None, :]
    
    # XYZ转线性RGB
    rgb_from_xyz = torch.tensor([
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252]
    ], dtype=lab.dtype, device=lab.device)
    
    # 维度适配：矩阵乘法
    shape = xyz.shape
    xyz_flat = xyz.reshape(-1, 3)  # (N, 3)
    linear_rgb_flat = xyz_flat @ rgb_from_xyz.T  # (N, 3)
    linear_rgb = linear_rgb_flat.reshape(shape)  # 恢复原形状
    
    # 线性RGB转sRGB（伽马校正）
    rgb = torch.where(
        linear_rgb > 0.0031308,
        1.055 * (linear_rgb ** (1/2.4)) - 0.055,
        12.92 * linear_rgb
    )
    
    # 确保输出在[0,1]范围内
    rgb = torch.clamp(rgb, 0.0, 1.0)
    return rgb

def match_and_blend_colors_torch(
    source_chunk: torch.Tensor, 
    reference_image: torch.Tensor, 
    strength: float
) -> torch.Tensor:
    """
    全GPU批量运算版本：将视频chunk的颜色匹配到参考图像并混合（支持B>1、T帧并行）
    
    Args:
        source_chunk (torch.Tensor): 视频chunk (B, C, T, H, W)，范围[-1, 1]
        reference_image (torch.Tensor): 参考图像 (B, C, 1, H, W)，范围[-1, 1]（B需与source_chunk一致）
        strength (float): 颜色校正强度 (0.0-1.0)，0.0无校正，1.0完全校正
    
    Returns:
        torch.Tensor: 颜色校正后的视频chunk (B, C, T, H, W)，范围[-1, 1]
    """
    # 强度为0直接返回原图
    if strength <= 0.0:
        return source_chunk.clone()
    
    # 验证强度范围
    if not 0.0 <= strength <= 1.0:
        raise ValueError(f"Strength必须在0.0-1.0之间，当前值：{strength}")
    
    # 验证输入形状（确保B一致，参考图T=1）
    B, C, T, H, W = source_chunk.shape
    assert reference_image.shape == (B, C, 1, H, W), \
        f"参考图像形状需为(B, C, 1, H, W)，当前为{reference_image.shape}"
    assert C == 3, f"仅支持3通道RGB图像，当前通道数：{C}"
    
    # 保持设备和数据类型一致
    device = source_chunk.device
    dtype = source_chunk.dtype
    reference_image = reference_image.to(device=device, dtype=dtype)
    
    # 1. 从[-1,1]转换到[0,1]（GPU上直接运算）
    source_01 = (source_chunk + 1.0) / 2.0
    ref_01 = (reference_image + 1.0) / 2.0
    
    # 2. 调整维度顺序：(B, C, T, H, W) → (B, T, H, W, C)（适配颜色空间转换）
    # 参考图：(B, C, 1, H, W) → (B, 1, H, W, C)
    source_permuted = source_01.permute(0, 2, 3, 4, 1)  # 通道移到最后一维
    ref_permuted = ref_01.permute(0, 2, 3, 4, 1)
    
    # 3. RGB转Lab（批量处理所有帧）
    source_lab = rgb_to_lab_torch(source_permuted)
    ref_lab = rgb_to_lab_torch(ref_permuted)  # (B, 1, H, W, 3)
    
    # 4. 批量颜色迁移：匹配L/a/b通道的均值和标准差（核心逻辑）
    # 计算参考图各通道的均值和标准差（对H、W维度求统计，保持B维度）
    ref_mean = ref_lab.mean(dim=[2, 3], keepdim=True)  # (B, 1, 1, 1, 3)
    ref_std = ref_lab.std(dim=[2, 3], keepdim=True, unbiased=False)  # (B, 1, 1, 1, 3)
    
    # 计算源视频各通道的均值和标准差（对H、W维度求统计，保持B、T维度）
    source_mean = source_lab.mean(dim=[2, 3], keepdim=True)  # (B, T, 1, 1, 3)
    source_std = source_lab.std(dim=[2, 3], keepdim=True, unbiased=False)  # (B, T, 1, 1, 3)
    
    # 避免标准差为0的除法错误（用1.0替代0）
    source_std_safe = torch.where(source_std < 1e-8, torch.ones_like(source_std), source_std)
    
    # 颜色迁移公式：(源 - 源均值) * (参考标准差/源标准差) + 参考均值
    corrected_lab = (source_lab - source_mean) * (ref_std / source_std_safe) + ref_mean
    
    # 5. Lab转RGB（批量转换所有校正后的帧）
    corrected_rgb_01 = lab_to_rgb_torch(corrected_lab)
    
    # 6. 批量混合原始帧和校正帧（按强度加权）
    blended_rgb_01 = (1 - strength) * source_permuted + strength * corrected_rgb_01
    
    # 7. 还原维度顺序和数值范围：(B, T, H, W, C) → (B, C, T, H, W)，范围[0,1]→[-1,1]
    blended_rgb_01 = blended_rgb_01.permute(0, 4, 1, 2, 3)  # 通道移回第二维
    blended_rgb_minus1_1 = (blended_rgb_01 * 2.0) - 1.0
    
    # 8. 确保输出格式正确（连续内存布局）
    output = blended_rgb_minus1_1.contiguous().to(device=device, dtype=dtype)
    
    return output

def _get_crop_biases() -> tuple[float, float]:
    """Read crop anchor from env. 0.5 = center (default). >0.5 shifts window down/right."""
    def _f(name, default):
        try:
            return max(0.0, min(1.0, float(os.environ.get(name, default))))
        except (TypeError, ValueError):
            return default
    return _f("FLASHTALK_COND_CROP_VERTICAL_BIAS", 0.5), _f("FLASHTALK_COND_CROP_HORIZONTAL_BIAS", 0.5)


def _biased_crop_offsets(final_h, final_w, target_h, target_w, v_bias, h_bias):
    margin_h = max(final_h - target_h, 0)
    margin_w = max(final_w - target_w, 0)
    top  = max(0, min(int(round(margin_h * v_bias)), margin_h))
    left = max(0, min(int(round(margin_w * h_bias)), margin_w))
    return top, left


def resize_and_centercrop(cond_image, target_size):
    """
    Resize (cover) then crop to target_size.
    Crop position is controlled by FLASHTALK_COND_CROP_VERTICAL_BIAS /
    FLASHTALK_COND_CROP_HORIZONTAL_BIAS in [0,1], default 0.5 (center).
    Set FLASHTALK_COND_CROP_VERTICAL_BIAS > 0.5 to keep more of the bottom
    (e.g. hands on desk).
    """
    if isinstance(cond_image, torch.Tensor):
        _, orig_h, orig_w = cond_image.shape
    else:
        orig_h, orig_w = cond_image.height, cond_image.width

    target_h, target_w = target_size
    scale = max(target_h / orig_h, target_w / orig_w)
    final_h = math.ceil(scale * orig_h)
    final_w = math.ceil(scale * orig_w)

    v_bias, h_bias = _get_crop_biases()
    top, left = _biased_crop_offsets(final_h, final_w, target_h, target_w, v_bias, h_bias)

    if isinstance(cond_image, torch.Tensor):
        if len(cond_image.shape) == 3:
            cond_image = cond_image[None]
        resized_tensor = nn.functional.interpolate(cond_image, size=(final_h, final_w), mode='nearest').contiguous()
        cropped_tensor = resized_tensor[:, :, top:top + target_h, left:left + target_w]
        cropped_tensor = cropped_tensor.squeeze(0)
    else:
        resized_image = cond_image.resize((final_w, final_h), resample=Image.BILINEAR)
        resized_tensor = torch.from_numpy(np.array(resized_image))[None, ...].permute(0, 3, 1, 2).contiguous()
        cropped_tensor = resized_tensor[:, :, top:top + target_h, left:left + target_w]
        cropped_tensor = cropped_tensor[:, :, None, :, :]

    return cropped_tensor

def loudness_norm(audio_array, sr=16000, lufs=-23):
    meter = pyln.Meter(sr)
    loudness = meter.integrated_loudness(audio_array)
    if abs(loudness) > 100:
        return audio_array
    normalized_audio = pyln.normalize.loudness(audio_array, loudness, lufs)
    return normalized_audio