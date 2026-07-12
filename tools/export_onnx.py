"""Export the trusted academic PyTorch bundle for production ONNX inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch import nn


class ConvBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False), nn.BatchNorm2d(out_ch), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
        )

    def forward(self, x):
        return self.block(x)


class WindowCNN(nn.Module):
    def __init__(self, base_channels: int = 16, dropout: float = 0.2) -> None:
        super().__init__()
        c1, c2, c3, c4 = [base_channels * value for value in (1, 2, 4, 8)]
        self.features = nn.Sequential(
            ConvBlock(1, c1), ConvBlock(c1, c2), ConvBlock(c2, c3), ConvBlock(c3, c4)
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(c4, 1)

    def forward(self, x):
        embedding = self.dropout(self.pool(self.features(x)).flatten(1))
        return self.head(embedding).squeeze(1), embedding


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=Path("backend/model/burst_detector"))
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    checkpoint = torch.load(bundle / "model.pt", map_location="cpu", weights_only=False)
    config = checkpoint.get("config", {})
    model_config = config.get("model", {})
    model = WindowCNN(
        base_channels=int(model_config.get("base_channels", 16)),
        dropout=float(model_config.get("dropout", 0.2)),
    )
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    output_path = bundle / "model.onnx"
    torch.onnx.export(
        model, torch.zeros(1, 1, 128, 128), output_path,
        input_names=["windows"], output_names=["logits", "embeddings"],
        dynamic_axes={"windows": {0: "batch"}, "logits": {0: "batch"}, "embeddings": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    runtime = {
        "schema_version": 1,
        "model_version": str(checkpoint.get("model_version", "unknown")),
        "model": model_config,
        "preprocess": config.get("preprocess", {}),
        "window": config.get("window", {}),
        "inference": config.get("inference", {}),
    }
    (bundle / "runtime_config.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Exported {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
