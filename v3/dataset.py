from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import shutil

from PIL import Image, ImageEnhance, ImageFilter

from v3.types import VISION_CLASSES, VisionDetection, clamp_bbox


DEFAULT_RAW_ROOT = Path("datasets/forza_ui/raw")
DEFAULT_DATASET_ROOT = Path("datasets/forza_ui/yolo")


def _read_candidates(metadata: dict) -> list[VisionDetection]:
    detections = []
    for item in metadata.get("candidates", []) or []:
        label = str(item.get("label", ""))
        bbox = tuple(float(v) for v in item.get("bbox", (0, 0, 0, 0)))
        confidence = float(item.get("confidence", 0.0) or 0.0)
        source = str(item.get("source", "metadata"))
        detection = VisionDetection(label=label, confidence=confidence, bbox=bbox, source=source, meta=item.get("meta", {}))
        if detection.is_trainable():
            detections.append(detection)
    return detections


def _load_raw_samples(raw_root: Path) -> list[tuple[Path, dict, list[VisionDetection]]]:
    rows = []
    for metadata_path in sorted(raw_root.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        image_path = metadata_path.parent / metadata.get("image", "image.png")
        if not image_path.exists():
            continue
        detections = _read_candidates(metadata)
        rows.append((image_path, metadata, detections))
    return rows


def _write_label(path: Path, detections: list[VisionDetection]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [detection.yolo_line() for detection in detections if detection.is_trainable()]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _adjust_bbox_for_crop(bbox: tuple[float, float, float, float], crop: tuple[float, float, float, float]):
    x1, y1, x2, y2 = clamp_bbox(bbox)
    cx1, cy1, cx2, cy2 = crop
    crop_w = max(0.001, cx2 - cx1)
    crop_h = max(0.001, cy2 - cy1)
    nx1 = (max(x1, cx1) - cx1) / crop_w
    ny1 = (max(y1, cy1) - cy1) / crop_h
    nx2 = (min(x2, cx2) - cx1) / crop_w
    ny2 = (min(y2, cy2) - cy1) / crop_h
    adjusted = clamp_bbox((nx1, ny1, nx2, ny2))
    if adjusted[2] - adjusted[0] < 0.01 or adjusted[3] - adjusted[1] < 0.01:
        return None
    return adjusted


def _augmentations(image: Image.Image, detections: list[VisionDetection]):
    yield "orig", image, detections
    yield "blur", image.filter(ImageFilter.GaussianBlur(radius=0.6)), detections
    yield "bright", ImageEnhance.Brightness(image).enhance(1.18), detections
    yield "contrast", ImageEnhance.Contrast(image).enhance(1.15), detections

    crop = (0.025, 0.025, 0.985, 0.985)
    left = int(crop[0] * image.width)
    top = int(crop[1] * image.height)
    right = int(crop[2] * image.width)
    bottom = int(crop[3] * image.height)
    cropped = image.crop((left, top, right, bottom)).resize(image.size)
    adjusted = []
    for detection in detections:
        bbox = _adjust_bbox_for_crop(detection.bbox, crop)
        if bbox:
            adjusted.append(
                VisionDetection(
                    label=detection.label,
                    confidence=detection.confidence,
                    bbox=bbox,
                    source=detection.source,
                    meta={**detection.meta, "augmentation": "crop"},
                )
            )
    yield "crop", cropped, adjusted

    small = image.resize((max(1, int(image.width * 0.82)), max(1, int(image.height * 0.82))))
    scaled = small.resize(image.size)
    yield "scale", scaled, detections


def _write_data_yaml(dataset_root: Path) -> None:
    names = "\n".join(f"  {index}: {name}" for index, name in enumerate(VISION_CLASSES))
    content = (
        f"path: {dataset_root.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        f"nc: {len(VISION_CLASSES)}\n"
        "names:\n"
        f"{names}\n"
    )
    (dataset_root / "data.yaml").write_text(content, encoding="utf-8")


def generate_yolo_dataset(
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    val_split: float = 0.2,
    augment: bool = True,
    seed: int = 20260528,
) -> dict:
    raw_root = Path(raw_root)
    dataset_root = Path(dataset_root)
    samples = _load_raw_samples(raw_root)
    if not samples:
        raise RuntimeError(f"No raw samples found under {raw_root}")

    if dataset_root.exists():
        shutil.rmtree(dataset_root)
    for split in ("train", "val"):
        (dataset_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (dataset_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    rows = list(samples)
    rng.shuffle(rows)
    val_count = max(1, int(len(rows) * val_split)) if len(rows) > 1 else 0
    image_count = 0
    labeled_count = 0
    class_counts = {name: 0 for name in VISION_CLASSES}
    for index, (image_path, metadata, detections) in enumerate(rows):
        split = "val" if val_count and index < val_count else "train"
        image = Image.open(image_path).convert("RGB")
        sample_id = metadata.get("sample_id", image_path.parent.name)
        variants = _augmentations(image, detections) if augment else [("orig", image, detections)]
        for suffix, variant, variant_detections in variants:
            stem = f"{sample_id}_{suffix}"
            out_image = dataset_root / "images" / split / f"{stem}.png"
            out_label = dataset_root / "labels" / split / f"{stem}.txt"
            variant.save(out_image)
            _write_label(out_label, variant_detections)
            image_count += 1
            if variant_detections:
                labeled_count += 1
            for detection in variant_detections:
                if detection.label in class_counts:
                    class_counts[detection.label] += 1

    _write_data_yaml(dataset_root)
    summary = {
        "raw_samples": len(samples),
        "images": image_count,
        "labeled_images": labeled_count,
        "dataset_root": str(dataset_root),
        "data_yaml": str(dataset_root / "data.yaml"),
        "class_counts": class_counts,
    }
    (dataset_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a YOLO dataset from V3 raw samples.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    parser.add_argument("--val-split", type=float, default=0.2)
    parser.add_argument("--no-augment", action="store_true")
    args = parser.parse_args(argv)
    summary = generate_yolo_dataset(
        raw_root=args.raw_root,
        dataset_root=args.dataset_root,
        val_split=args.val_split,
        augment=not args.no_augment,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
