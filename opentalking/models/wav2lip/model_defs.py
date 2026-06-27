from __future__ import annotations

import torch
from torch import nn

from .layers import Conv2d, Conv2dTranspose


class Wav2Lip256(nn.Module):
    def __init__(self) -> None:
        super().__init__()

        self.face_encoder_blocks = nn.ModuleList(
            [
                nn.Sequential(Conv2d(6, 16, kernel_size=7, stride=1, padding=3)),
                nn.Sequential(
                    Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
                    Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(128, 256, kernel_size=3, stride=2, padding=1),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(256, 512, kernel_size=3, stride=2, padding=1),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(512, 512, kernel_size=3, stride=2, padding=1),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(512, 512, kernel_size=4, stride=1, padding=0),
                    Conv2d(512, 512, kernel_size=1, stride=1, padding=0),
                ),
            ]
        )

        self.audio_encoder = nn.Sequential(
            Conv2d(1, 32, kernel_size=3, stride=1, padding=1),
            Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(32, 64, kernel_size=3, stride=(3, 1), padding=1),
            Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(64, 128, kernel_size=3, stride=3, padding=1),
            Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(128, 256, kernel_size=3, stride=(3, 2), padding=1),
            Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(256, 512, kernel_size=3, stride=1, padding=0),
            Conv2d(512, 512, kernel_size=1, stride=1, padding=0),
        )

        self.face_decoder_blocks = nn.ModuleList(
            [
                nn.Sequential(Conv2d(512, 512, kernel_size=1, stride=1, padding=0)),
                nn.Sequential(
                    Conv2dTranspose(1024, 512, kernel_size=4, stride=1, padding=0),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(1024, 512, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(1024, 512, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(768, 384, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(384, 384, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(384, 384, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(512, 256, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(320, 128, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(160, 64, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                ),
            ]
        )

        self.output_block = nn.Sequential(
            Conv2d(80, 32, kernel_size=3, stride=1, padding=1),
            nn.Conv2d(32, 3, kernel_size=1, stride=1, padding=0),
            nn.Sigmoid(),
        )

    def forward(self, audio_sequences, face_sequences):
        batch_size = audio_sequences.size(0)
        input_dim_size = len(face_sequences.size())

        if input_dim_size > 4:
            audio_sequences = torch.cat(
                [audio_sequences[:, i] for i in range(audio_sequences.size(1))],
                dim=0,
            )
            face_sequences = torch.cat(
                [face_sequences[:, :, i] for i in range(face_sequences.size(2))],
                dim=0,
            )

        audio_embedding = self.audio_encoder(audio_sequences)

        feats = []
        x = face_sequences
        for block in self.face_encoder_blocks:
            x = block(x)
            feats.append(x)

        x = audio_embedding
        for block in self.face_decoder_blocks:
            x = block(x)
            x = torch.cat((x, feats[-1]), dim=1)
            feats.pop()

        x = self.output_block(x)

        if input_dim_size > 4:
            x = torch.split(x, batch_size, dim=0)
            outputs = torch.stack(x, dim=2)
        else:
            outputs = x
        return outputs


class _SpatialAttention(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(2, 1, kernel_size=7, padding=3, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = torch.mean(x, dim=1, keepdim=True)
        max_out, _ = torch.max(x, dim=1, keepdim=True)
        return self.sigmoid(self.conv1(torch.cat([avg_out, max_out], dim=1)))


class _SAM(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.sa = _SpatialAttention()

    def forward(self, spatial_features, semantic_features):
        return semantic_features * self.sa(spatial_features) + semantic_features


class Wav2Lip384(nn.Module):
    def __init__(self) -> None:
        super().__init__()

        self.sam = _SAM()
        self.face_encoder_blocks = nn.ModuleList(
            [
                nn.Sequential(
                    Conv2d(6, 16, kernel_size=7, stride=1, padding=3),
                    Conv2d(16, 16, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(16, 16, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(16, 16, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
                    Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(128, 256, kernel_size=3, stride=2, padding=1),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(256, 512, kernel_size=3, stride=2, padding=1),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(512, 1024, kernel_size=3, stride=2, padding=1),
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=0),
                    Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0),
                    Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0),
                ),
            ]
        )

        self.audio_encoder = nn.Sequential(
            Conv2d(1, 32, kernel_size=3, stride=1, padding=1),
            Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(32, 64, kernel_size=3, stride=(3, 1), padding=1),
            Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(64, 128, kernel_size=3, stride=3, padding=1),
            Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(128, 256, kernel_size=3, stride=(3, 2), padding=1),
            Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(256, 512, kernel_size=3, stride=1, padding=1),
            Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
            Conv2d(512, 1024, kernel_size=3, stride=1, padding=0),
            Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0),
        )
        self.audio_refine = nn.Sequential(
            Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0),
            Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0),
        )

        self.face_decoder_blocks = nn.ModuleList(
            [
                nn.Sequential(Conv2d(1024, 1024, kernel_size=1, stride=1, padding=0)),
                nn.Sequential(
                    Conv2dTranspose(2048, 1024, kernel_size=3, stride=1, padding=0),
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(2048, 1024, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(1024, 1024, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(1536, 768, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(768, 768, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(768, 768, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(1024, 512, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(640, 256, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(320, 128, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                ),
                nn.Sequential(
                    Conv2dTranspose(160, 64, kernel_size=3, stride=2, padding=1, output_padding=1),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                    Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                ),
            ]
        )

        self.output_block = nn.Sequential(
            Conv2d(80, 32, kernel_size=3, stride=1, padding=1),
            nn.Conv2d(32, 3, kernel_size=1, stride=1, padding=0),
            nn.Sigmoid(),
        )

    def forward(self, audio_sequences, face_sequences):
        batch_size = audio_sequences.size(0)
        input_dim_size = len(face_sequences.size())

        if input_dim_size > 4:
            audio_sequences = torch.cat(
                [audio_sequences[:, i] for i in range(audio_sequences.size(1))],
                dim=0,
            )
            face_sequences = torch.cat(
                [face_sequences[:, :, i] for i in range(face_sequences.size(2))],
                dim=0,
            )

        audio_embedding = self.audio_encoder(audio_sequences)

        feats = []
        x = face_sequences
        for block in self.face_encoder_blocks:
            x = block(x)
            feats.append(x)

        x = audio_embedding
        for block in self.face_decoder_blocks:
            x = block(x)
            x = self.sam(feats[-1], x)
            x = torch.cat((x, feats[-1]), dim=1)
            feats.pop()

        x = self.output_block(x)

        if input_dim_size > 4:
            x = torch.split(x, batch_size, dim=0)
            outputs = torch.stack(x, dim=2)
        else:
            outputs = x
        return outputs
