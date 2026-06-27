from __future__ import annotations

from enum import Enum
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_s3fd_path() -> Path:
    return _repo_root() / "models" / "s3fd.pth"


class LandmarksType(Enum):
    _2D = 1
    _2halfD = 2
    _3D = 3


class _BaseFaceDetector:
    def __init__(self, device: str, verbose: bool = False) -> None:
        self.device = device
        self.verbose = verbose


class _L2Norm(nn.Module):
    def __init__(self, n_channels: int, scale: float = 1.0) -> None:
        super().__init__()
        self.eps = 1e-10
        self.weight = nn.Parameter(torch.Tensor(n_channels))
        self.weight.data *= 0.0
        self.weight.data += scale

    def forward(self, x):
        norm = x.pow(2).sum(dim=1, keepdim=True).sqrt() + self.eps
        return x / norm * self.weight.view(1, -1, 1, 1)


class _S3FD(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.conv1_1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1)
        self.conv1_2 = nn.Conv2d(64, 64, kernel_size=3, stride=1, padding=1)
        self.conv2_1 = nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1)
        self.conv2_2 = nn.Conv2d(128, 128, kernel_size=3, stride=1, padding=1)
        self.conv3_1 = nn.Conv2d(128, 256, kernel_size=3, stride=1, padding=1)
        self.conv3_2 = nn.Conv2d(256, 256, kernel_size=3, stride=1, padding=1)
        self.conv3_3 = nn.Conv2d(256, 256, kernel_size=3, stride=1, padding=1)
        self.conv4_1 = nn.Conv2d(256, 512, kernel_size=3, stride=1, padding=1)
        self.conv4_2 = nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1)
        self.conv4_3 = nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1)
        self.conv5_1 = nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1)
        self.conv5_2 = nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1)
        self.conv5_3 = nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1)
        self.fc6 = nn.Conv2d(512, 1024, kernel_size=3, stride=1, padding=3)
        self.fc7 = nn.Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0)
        self.conv6_1 = nn.Conv2d(1024, 256, kernel_size=1, stride=1, padding=0)
        self.conv6_2 = nn.Conv2d(256, 512, kernel_size=3, stride=2, padding=1)
        self.conv7_1 = nn.Conv2d(512, 128, kernel_size=1, stride=1, padding=0)
        self.conv7_2 = nn.Conv2d(128, 256, kernel_size=3, stride=2, padding=1)

        self.conv3_3_norm = _L2Norm(256, scale=10)
        self.conv4_3_norm = _L2Norm(512, scale=8)
        self.conv5_3_norm = _L2Norm(512, scale=5)

        self.conv3_3_norm_mbox_conf = nn.Conv2d(256, 4, kernel_size=3, stride=1, padding=1)
        self.conv3_3_norm_mbox_loc = nn.Conv2d(256, 4, kernel_size=3, stride=1, padding=1)
        self.conv4_3_norm_mbox_conf = nn.Conv2d(512, 2, kernel_size=3, stride=1, padding=1)
        self.conv4_3_norm_mbox_loc = nn.Conv2d(512, 4, kernel_size=3, stride=1, padding=1)
        self.conv5_3_norm_mbox_conf = nn.Conv2d(512, 2, kernel_size=3, stride=1, padding=1)
        self.conv5_3_norm_mbox_loc = nn.Conv2d(512, 4, kernel_size=3, stride=1, padding=1)
        self.fc7_mbox_conf = nn.Conv2d(1024, 2, kernel_size=3, stride=1, padding=1)
        self.fc7_mbox_loc = nn.Conv2d(1024, 4, kernel_size=3, stride=1, padding=1)
        self.conv6_2_mbox_conf = nn.Conv2d(512, 2, kernel_size=3, stride=1, padding=1)
        self.conv6_2_mbox_loc = nn.Conv2d(512, 4, kernel_size=3, stride=1, padding=1)
        self.conv7_2_mbox_conf = nn.Conv2d(256, 2, kernel_size=3, stride=1, padding=1)
        self.conv7_2_mbox_loc = nn.Conv2d(256, 4, kernel_size=3, stride=1, padding=1)

    def forward(self, x):
        h = F.relu(self.conv1_1(x))
        h = F.relu(self.conv1_2(h))
        h = F.max_pool2d(h, 2, 2)

        h = F.relu(self.conv2_1(h))
        h = F.relu(self.conv2_2(h))
        h = F.max_pool2d(h, 2, 2)

        h = F.relu(self.conv3_1(h))
        h = F.relu(self.conv3_2(h))
        h = F.relu(self.conv3_3(h))
        f3_3 = h
        h = F.max_pool2d(h, 2, 2)

        h = F.relu(self.conv4_1(h))
        h = F.relu(self.conv4_2(h))
        h = F.relu(self.conv4_3(h))
        f4_3 = h
        h = F.max_pool2d(h, 2, 2)

        h = F.relu(self.conv5_1(h))
        h = F.relu(self.conv5_2(h))
        h = F.relu(self.conv5_3(h))
        f5_3 = h
        h = F.max_pool2d(h, 2, 2)

        h = F.relu(self.fc6(h))
        h = F.relu(self.fc7(h))
        ffc7 = h
        h = F.relu(self.conv6_1(h))
        h = F.relu(self.conv6_2(h))
        f6_2 = h
        h = F.relu(self.conv7_1(h))
        h = F.relu(self.conv7_2(h))
        f7_2 = h

        f3_3 = self.conv3_3_norm(f3_3)
        f4_3 = self.conv4_3_norm(f4_3)
        f5_3 = self.conv5_3_norm(f5_3)

        cls1 = self.conv3_3_norm_mbox_conf(f3_3)
        reg1 = self.conv3_3_norm_mbox_loc(f3_3)
        cls2 = self.conv4_3_norm_mbox_conf(f4_3)
        reg2 = self.conv4_3_norm_mbox_loc(f4_3)
        cls3 = self.conv5_3_norm_mbox_conf(f5_3)
        reg3 = self.conv5_3_norm_mbox_loc(f5_3)
        cls4 = self.fc7_mbox_conf(ffc7)
        reg4 = self.fc7_mbox_loc(ffc7)
        cls5 = self.conv6_2_mbox_conf(f6_2)
        reg5 = self.conv6_2_mbox_loc(f6_2)
        cls6 = self.conv7_2_mbox_conf(f7_2)
        reg6 = self.conv7_2_mbox_loc(f7_2)

        chunk = torch.chunk(cls1, 4, 1)
        bmax = torch.max(torch.max(chunk[0], chunk[1]), chunk[2])
        cls1 = torch.cat([bmax, chunk[3]], dim=1)
        return [cls1, reg1, cls2, reg2, cls3, reg3, cls4, reg4, cls5, reg5, cls6, reg6]


def _nms(dets: np.ndarray, thresh: float) -> list[int]:
    if len(dets) == 0:
        return []
    x1, y1, x2, y2, scores = dets[:, 0], dets[:, 1], dets[:, 2], dets[:, 3], dets[:, 4]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        overlap = w * h / (areas[i] + areas[order[1:]] - w * h)
        inds = np.where(overlap <= thresh)[0]
        order = order[inds + 1]
    return keep


def _decode(loc: torch.Tensor, priors: torch.Tensor, variances: list[float]) -> torch.Tensor:
    boxes = torch.cat(
        (
            priors[:, :2] + loc[:, :2] * variances[0] * priors[:, 2:],
            priors[:, 2:] * torch.exp(loc[:, 2:] * variances[1]),
        ),
        1,
    )
    boxes[:, :2] -= boxes[:, 2:] / 2
    boxes[:, 2:] += boxes[:, :2]
    return boxes


def _batch_decode(loc: torch.Tensor, priors: torch.Tensor, variances: list[float]) -> torch.Tensor:
    boxes = torch.cat(
        (
            priors[:, :, :2] + loc[:, :, :2] * variances[0] * priors[:, :, 2:],
            priors[:, :, 2:] * torch.exp(loc[:, :, 2:] * variances[1]),
        ),
        2,
    )
    boxes[:, :, :2] -= boxes[:, :, 2:] / 2
    boxes[:, :, 2:] += boxes[:, :, :2]
    return boxes


def _batch_detect(net: _S3FD, images: np.ndarray, device: str) -> np.ndarray:
    images = images - np.array([104, 117, 123])
    images = images.transpose(0, 3, 1, 2)
    tensor = torch.from_numpy(images).float().to(device)
    batch_size = tensor.size(0)
    with torch.no_grad():
        outputs = net(tensor)

    for idx in range(len(outputs) // 2):
        outputs[idx * 2] = F.softmax(outputs[idx * 2], dim=1)
    outputs = [item.data.cpu() for item in outputs]

    bboxlist = []
    for idx in range(len(outputs) // 2):
        ocls, oreg = outputs[idx * 2], outputs[idx * 2 + 1]
        stride = 2 ** (idx + 2)
        positions = zip(*np.where(ocls[:, 1, :, :] > 0.05))
        for _, hindex, windex in positions:
            axc = stride / 2 + windex * stride
            ayc = stride / 2 + hindex * stride
            score = ocls[:, 1, hindex, windex]
            loc = oreg[:, :, hindex, windex].contiguous().view(batch_size, 1, 4)
            priors = torch.tensor([[axc, ayc, stride * 4, stride * 4]], dtype=torch.float32).view(1, 1, 4)
            box = _batch_decode(loc, priors, [0.1, 0.2])
            bboxlist.append(torch.cat([box[:, 0], score.unsqueeze(1)], 1).cpu().numpy())
    if not bboxlist:
        return np.zeros((1, batch_size, 5))
    return np.array(bboxlist)


class _SFDDetector(_BaseFaceDetector):
    def __init__(
        self,
        device: str,
        path_to_detector: str | Path | None = None,
        verbose: bool = False,
    ) -> None:
        super().__init__(device, verbose)
        detector_path = Path(path_to_detector).expanduser() if path_to_detector else _default_s3fd_path()
        if not detector_path.is_file():
            raise FileNotFoundError(f"Missing s3fd checkpoint: {detector_path}")
        model_weights = torch.load(detector_path, map_location=device)
        self.face_detector = _S3FD()
        self.face_detector.load_state_dict(model_weights)
        self.face_detector.to(device)
        self.face_detector.eval()

    def detect_from_batch(self, images: np.ndarray) -> list[list[np.ndarray]]:
        bboxlists = _batch_detect(self.face_detector, images, device=self.device)
        keeps = [_nms(bboxlists[:, i, :], 0.3) for i in range(bboxlists.shape[1])]
        filtered = [bboxlists[keep, i, :] for i, keep in enumerate(keeps)]
        return [[row for row in bboxlist if row[-1] > 0.5] for bboxlist in filtered]


class FaceAlignment:
    def __init__(
        self,
        landmarks_type: LandmarksType,
        device: str = "cuda",
        flip_input: bool = False,
        verbose: bool = False,
        path_to_detector: str | Path | None = None,
    ) -> None:
        self.device = device
        self.flip_input = flip_input
        self.landmarks_type = landmarks_type
        self.verbose = verbose
        self.face_detector = _SFDDetector(
            device=device,
            verbose=verbose,
            path_to_detector=path_to_detector,
        )

    def get_detections_for_batch(self, images: np.ndarray) -> list[tuple[int, int, int, int] | None]:
        detections = self.face_detector.detect_from_batch(images[..., ::-1].copy())
        results: list[tuple[int, int, int, int] | None] = []
        for det in detections:
            if len(det) == 0:
                results.append(None)
                continue
            x1, y1, x2, y2 = map(int, np.clip(det[0][:-1], 0, None))
            results.append((x1, y1, x2, y2))
        return results
