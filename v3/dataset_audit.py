from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from v3.types import VISION_CLASSES


DEFAULT_RAW_ROOT = Path("datasets/forza_ui/raw")
DEFAULT_DATASET_ROOT = Path("datasets/forza_ui/yolo")


DEFAULT_CLASS_TARGETS = {
    "pause_story_focus": 100,
    "pause_vehicle_focus": 100,
    "pause_creative_hub_focus": 80,
    "eventlab_card_focus": 120,
    "my_cars_card_focus": 120,
    "vehicle_mastery_focus": 100,
    "race_menu": 80,
    "race_result": 80,
    "post_race_next": 80,
    "modal_warning": 120,
    "pause_my_horizon_focus": 80,
    "pause_online_focus": 80,
    "pause_store_focus": 80,
    "design_card_focus": 50,
    "color_select": 50,
    "car_preview": 50,
}


DEFAULT_SCREEN_TARGETS = {
    "pause_story": 80,
    "pause_vehicle_entry": 80,
    "pause_creative_hub": 60,
    "eventlab_home": 80,
    "eventlab_events": 100,
    "eventlab_favorites": 60,
    "eventlab_filter": 60,
    "eventlab_my_cars": 100,
    "eventlab_race_type": 40,
    "race_pause_menu": 60,
    "vehicle_buy_grid": 100,
    "manufacturer_grid": 80,
    "autoshow_buy_sell": 40,
    "color_select": 40,
    "purchase_confirm": 40,
    "skill_points_exhausted": 30,
    "race_menu": 70,
    "race_result": 60,
    "post_race_next": 60,
    "race_hud": 40,
    "free_roam_hud": 40,
    "idle_showcase": 40,
    "loading_transition": 40,
    "controller_disconnected": 20,
    "modal_warning": 100,
}


COLLECTION_HINTS = {
    "race_result": "跑完短 EventLab 后停在结算页，多采继续/下一站/奖励动画前后。",
    "post_race_next": "赛后继续页、下一站页、按 B/继续前后都采，尤其焦点移动后的状态。",
    "color_select": "买车流程进入颜色选择页，采出厂颜色/设计推荐/确认前后。",
    "design_card_focus": "买车设计页采不同设计卡、推荐设计和空设计位。",
    "car_preview": "车辆展示/待机页采有无 UI、A/B/Menu 唤醒前后。",
    "my_cars_card_focus": "EventLab 我的车辆/车展车辆网格里采 22B、非 22B、不同列、不同滚动位置。",
    "eventlab_card_focus": "EventLab 首页和赛事列表采各分页、左中右卡片、目标赛事和非目标赛事。",
    "pause_creative_hub_focus": "暂停菜单创意中心采未锁、带锁、不同焦点卡片。",
    "race_menu": "赛事开始菜单采开始比赛、难度设置、起跑排位、退出比赛焦点。",
    "manufacturer_grid": "制造商表格采顶部、中部、底部、斯巴鲁、现代、漂移方程式等不同焦点。",
    "vehicle_buy_grid": "购买车辆网格采品牌页、22B、相邻车、左侧详情、滚动条可滑状态。",
    "eventlab_filter": "筛选弹窗采收藏空框、收藏有勾、焦点在性能等级/车辆类型/制造商。",
    "race_pause_menu": "比赛中按菜单采带锁创意中心/车辆页，再 LB 到剧情页采返回/退出比赛。",
}


@dataclass
class ClassGap:
    name: str
    count: int
    train_count: int
    val_count: int
    target: int
    deficit: int
    priority: str
    hint: str = ""


@dataclass
class ScreenGap:
    screen: str
    count: int
    target: int
    deficit: int
    priority: str
    hint: str = ""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_label_file(path: Path) -> tuple[list[int], list[str]]:
    class_ids: list[int] = []
    errors: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        parts = text.split()
        if len(parts) != 5:
            errors.append(f"{path}:{line_no}: expected 5 columns")
            continue
        try:
            class_id = int(float(parts[0]))
            values = [float(value) for value in parts[1:]]
        except ValueError:
            errors.append(f"{path}:{line_no}: non-numeric value")
            continue
        if class_id < 0 or class_id >= len(VISION_CLASSES):
            errors.append(f"{path}:{line_no}: class id {class_id} out of range")
            continue
        if any(value < 0.0 or value > 1.0 for value in values):
            errors.append(f"{path}:{line_no}: normalized bbox value outside 0..1")
            continue
        if values[2] <= 0.0 or values[3] <= 0.0:
            errors.append(f"{path}:{line_no}: non-positive bbox size")
            continue
        class_ids.append(class_id)
    return class_ids, errors


def _find_image_for_label(dataset_root: Path, label_path: Path) -> Path | None:
    rel = label_path.relative_to(dataset_root / "labels")
    image_dir = dataset_root / "images" / rel.parent
    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        candidate = image_dir / f"{label_path.stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _priority(deficit: int, target: int) -> str:
    if deficit <= 0:
        return "ok"
    if target <= 0:
        return "low"
    ratio = deficit / target
    if ratio >= 0.75:
        return "critical"
    if ratio >= 0.4:
        return "high"
    return "medium"


def _class_hint(name: str) -> str:
    return COLLECTION_HINTS.get(name, "")


def _screen_hint(screen: str) -> str:
    return COLLECTION_HINTS.get(screen, "")


def _audit_yolo_labels(dataset_root: Path) -> dict[str, Any]:
    label_root = dataset_root / "labels"
    image_root = dataset_root / "images"
    label_files = sorted(label_root.glob("*/*.txt")) if label_root.exists() else []
    image_files = sorted(
        path
        for path in image_root.glob("*/*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    ) if image_root.exists() else []

    class_counts = Counter()
    split_counts: dict[str, Counter] = defaultdict(Counter)
    images_with_class: dict[str, set[str]] = defaultdict(set)
    empty_labels: list[str] = []
    missing_images: list[str] = []
    invalid_lines: list[str] = []
    signature_counts = Counter()

    for label_path in label_files:
        split = label_path.parent.name
        class_ids, errors = _parse_label_file(label_path)
        invalid_lines.extend(errors)
        image_path = _find_image_for_label(dataset_root, label_path)
        if image_path is None:
            missing_images.append(str(label_path))
        if not class_ids:
            empty_labels.append(str(label_path))
        signature = "|".join(label_path.read_text(encoding="utf-8").strip().splitlines())
        if signature:
            signature_counts[signature] += 1
        for class_id in class_ids:
            name = VISION_CLASSES[class_id]
            class_counts[name] += 1
            split_counts[split][name] += 1
            images_with_class[name].add(str(label_path))

    image_rel = {
        str(path.relative_to(image_root)).replace("\\", "/")
        for path in image_files
    }
    label_rel = {
        str(path.relative_to(label_root)).replace("\\", "/").rsplit(".", 1)[0]
        for path in label_files
    }
    orphan_images = sorted(
        rel for rel in image_rel if rel.rsplit(".", 1)[0] not in label_rel
    )
    duplicate_label_signatures = sum(count - 1 for count in signature_counts.values() if count > 1)

    return {
        "label_files": len(label_files),
        "image_files": len(image_files),
        "class_counts": dict(class_counts),
        "split_counts": {split: dict(counter) for split, counter in split_counts.items()},
        "images_with_class": {name: len(paths) for name, paths in images_with_class.items()},
        "empty_label_files": len(empty_labels),
        "empty_label_examples": empty_labels[:12],
        "missing_images": len(missing_images),
        "missing_image_examples": missing_images[:12],
        "orphan_images": len(orphan_images),
        "orphan_image_examples": orphan_images[:12],
        "invalid_label_lines": len(invalid_lines),
        "invalid_label_examples": invalid_lines[:12],
        "duplicate_label_signatures": duplicate_label_signatures,
    }


def _audit_summary_file(dataset_root: Path) -> dict[str, Any]:
    summary_path = dataset_root / "summary.json"
    if not summary_path.exists():
        return {}
    summary = _read_json(summary_path)
    return {
        "raw_samples": int(summary.get("raw_samples", 0) or 0),
        "images": int(summary.get("images", 0) or 0),
        "labeled_images": int(summary.get("labeled_images", 0) or 0),
        "class_counts": dict(summary.get("class_counts") or {}),
    }


def _audit_raw(raw_root: Path) -> dict[str, Any]:
    metadata_files = sorted(raw_root.glob("*/metadata.json")) if raw_root.exists() else []
    screens = Counter()
    tabs = Counter()
    selected = Counter()
    candidate_labels = Counter()
    window_sizes = Counter()
    missing_images = 0
    empty_candidates = 0

    for metadata_path in metadata_files:
        try:
            metadata = _read_json(metadata_path)
        except Exception:
            continue
        image_path = metadata_path.parent / str(metadata.get("image", "image.png"))
        if not image_path.exists():
            missing_images += 1
        understanding = metadata.get("understanding") or {}
        screens[str(understanding.get("screen", "") or "unknown")] += 1
        tab = str(understanding.get("active_tab", "") or "")
        if tab:
            tabs[tab] += 1
        item = str(understanding.get("selected_item", "") or "")
        if item:
            selected[item] += 1
        window = metadata.get("window") or {}
        width = window.get("width")
        height = window.get("height")
        if width and height:
            window_sizes[f"{width}x{height}"] += 1
        candidates = metadata.get("candidates") or []
        if not candidates:
            empty_candidates += 1
        for candidate in candidates:
            label = str(candidate.get("label", "") or "")
            if label:
                candidate_labels[label] += 1

    return {
        "metadata_files": len(metadata_files),
        "missing_images": missing_images,
        "empty_candidates": empty_candidates,
        "screens": dict(screens),
        "active_tabs_top": dict(tabs.most_common(30)),
        "selected_items_top": dict(selected.most_common(40)),
        "candidate_labels": dict(candidate_labels),
        "window_sizes": dict(window_sizes),
    }


def _build_class_gaps(
    class_counts: dict[str, int],
    split_counts: dict[str, dict[str, int]],
    targets: dict[str, int],
) -> list[ClassGap]:
    gaps = []
    for name in VISION_CLASSES:
        target = int(targets.get(name, 0))
        count = int(class_counts.get(name, 0) or 0)
        train_count = int((split_counts.get("train") or {}).get(name, 0) or 0)
        val_count = int((split_counts.get("val") or {}).get(name, 0) or 0)
        deficit = max(0, target - count)
        gaps.append(
            ClassGap(
                name=name,
                count=count,
                train_count=train_count,
                val_count=val_count,
                target=target,
                deficit=deficit,
                priority=_priority(deficit, target),
                hint=_class_hint(name),
            )
        )
    return sorted(gaps, key=lambda gap: (gap.priority != "critical", gap.priority != "high", -gap.deficit, gap.name))


def _build_screen_gaps(screens: dict[str, int], targets: dict[str, int]) -> list[ScreenGap]:
    gaps = []
    for screen, target in sorted(targets.items()):
        count = int(screens.get(screen, 0) or 0)
        deficit = max(0, int(target) - count)
        gaps.append(
            ScreenGap(
                screen=screen,
                count=count,
                target=int(target),
                deficit=deficit,
                priority=_priority(deficit, int(target)),
                hint=_screen_hint(screen),
            )
        )
    return sorted(gaps, key=lambda gap: (gap.priority != "critical", gap.priority != "high", -gap.deficit, gap.screen))


def audit_dataset(
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    dataset_root: str | Path = DEFAULT_DATASET_ROOT,
    class_targets: dict[str, int] | None = None,
    screen_targets: dict[str, int] | None = None,
) -> dict[str, Any]:
    raw_root = Path(raw_root)
    dataset_root = Path(dataset_root)
    class_targets = {**DEFAULT_CLASS_TARGETS, **(class_targets or {})}
    screen_targets = {**DEFAULT_SCREEN_TARGETS, **(screen_targets or {})}

    yolo = _audit_yolo_labels(dataset_root)
    summary = _audit_summary_file(dataset_root)
    raw = _audit_raw(raw_root)

    class_counts = dict(yolo.get("class_counts") or {})
    if not class_counts and summary:
        class_counts = dict(summary.get("class_counts") or {})
    class_gaps = _build_class_gaps(class_counts, yolo.get("split_counts") or {}, class_targets)
    screen_gaps = _build_screen_gaps(raw.get("screens") or {}, screen_targets)

    return {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "raw_root": str(raw_root),
        "dataset_root": str(dataset_root),
        "summary": summary,
        "yolo": yolo,
        "raw": raw,
        "class_targets": class_targets,
        "screen_targets": screen_targets,
        "class_gaps": [asdict(gap) for gap in class_gaps],
        "screen_gaps": [asdict(gap) for gap in screen_gaps],
        "next_collection": build_collection_plan(class_gaps, screen_gaps),
    }


def build_collection_plan(class_gaps: list[ClassGap], screen_gaps: list[ScreenGap], limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gap in class_gaps:
        if gap.deficit <= 0:
            continue
        rows.append(
            {
                "kind": "yolo_class",
                "name": gap.name,
                "priority": gap.priority,
                "need": gap.deficit,
                "current": gap.count,
                "target": gap.target,
                "hint": gap.hint,
            }
        )
    for gap in screen_gaps:
        if gap.deficit <= 0:
            continue
        rows.append(
            {
                "kind": "screen",
                "name": gap.screen,
                "priority": gap.priority,
                "need": gap.deficit,
                "current": gap.count,
                "target": gap.target,
                "hint": gap.hint,
            }
        )
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "ok": 4}
    rows.sort(key=lambda row: (priority_order.get(str(row["priority"]), 9), -int(row["need"]), str(row["kind"]), str(row["name"])))
    return rows[:limit]


def render_markdown(report: dict[str, Any]) -> str:
    yolo = report.get("yolo") or {}
    raw = report.get("raw") or {}
    lines = [
        "# V3 Dataset Audit",
        "",
        f"- created_at: `{report.get('created_at', '')}`",
        f"- raw_root: `{report.get('raw_root', '')}`",
        f"- dataset_root: `{report.get('dataset_root', '')}`",
        f"- raw metadata: `{raw.get('metadata_files', 0)}`",
        f"- YOLO images: `{yolo.get('image_files', 0)}`",
        f"- YOLO labels: `{yolo.get('label_files', 0)}`",
        f"- empty label files: `{yolo.get('empty_label_files', 0)}`",
        f"- missing label images: `{yolo.get('missing_images', 0)}`",
        f"- invalid label lines: `{yolo.get('invalid_label_lines', 0)}`",
        f"- possible duplicate label signatures: `{yolo.get('duplicate_label_signatures', 0)}`",
        "",
        "## 优先补采",
        "",
    ]
    plan = report.get("next_collection") or []
    if not plan:
        lines.append("- 当前目标配额已满足。")
    else:
        for row in plan:
            hint = f" - {row['hint']}" if row.get("hint") else ""
            lines.append(
                f"- `{row['priority']}` `{row['kind']}` `{row['name']}`: "
                f"{row['current']}/{row['target']}，还缺 `{row['need']}`{hint}"
            )

    lines.extend(["", "## YOLO 类别缺口", ""])
    lines.append("| class | count | train | val | target | deficit | priority |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for gap in report.get("class_gaps", []):
        lines.append(
            f"| `{gap['name']}` | {gap['count']} | {gap['train_count']} | {gap['val_count']} | "
            f"{gap['target']} | {gap['deficit']} | {gap['priority']} |"
        )

    lines.extend(["", "## 页面语义缺口", ""])
    lines.append("| screen | count | target | deficit | priority |")
    lines.append("|---|---:|---:|---:|---|")
    for gap in report.get("screen_gaps", []):
        lines.append(
            f"| `{gap['screen']}` | {gap['count']} | {gap['target']} | {gap['deficit']} | {gap['priority']} |"
        )

    lines.extend(["", "## 窗口尺寸分布", ""])
    sizes = raw.get("window_sizes") or {}
    if sizes:
        for size, count in sorted(sizes.items(), key=lambda item: (-int(item[1]), item[0]))[:20]:
            lines.append(f"- `{size}`: {count}")
    else:
        lines.append("- 未读取到窗口尺寸。")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], output_dir: str | Path = "reports") -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = output_dir / f"dataset_audit_{slug}.json"
    md_path = output_dir / f"dataset_audit_{slug}.md"
    json_text = json.dumps(report, ensure_ascii=False, indent=2)
    md_text = render_markdown(report)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    (output_dir / "dataset_audit_latest.json").write_text(json_text, encoding="utf-8")
    (output_dir / "dataset_audit_latest.md").write_text(md_text, encoding="utf-8")
    return json_path, md_path


def _target_overrides(items: list[str]) -> dict[str, int]:
    overrides = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"target override must be name=count, got: {item}")
        name, value = item.split("=", 1)
        overrides[name.strip()] = int(value)
    return overrides


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Forza UI YOLO/raw sample balance and print a targeted collection plan.")
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--class-target", action="append", default=[], help="Override class target, e.g. race_result=120")
    parser.add_argument("--screen-target", action="append", default=[], help="Override screen target, e.g. eventlab_filter=80")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    report = audit_dataset(
        raw_root=args.raw_root,
        dataset_root=args.dataset_root,
        class_targets=_target_overrides(args.class_target),
        screen_targets=_target_overrides(args.screen_target),
    )
    if not args.no_write:
        json_path, md_path = write_report(report, args.output_dir)
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
