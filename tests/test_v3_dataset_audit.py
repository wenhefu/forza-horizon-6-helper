import json

from v3.dataset import _write_data_yaml
from v3.dataset_audit import audit_dataset, render_markdown


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_dataset_audit_reports_class_and_screen_deficits(tmp_path):
    dataset_root = tmp_path / "yolo"
    raw_root = tmp_path / "raw"

    _write(dataset_root / "labels" / "train" / "race_result.txt", "7 0.500000 0.500000 0.200000 0.200000\n")
    _write(dataset_root / "images" / "train" / "race_result.png", "fake image")
    _write(dataset_root / "labels" / "val" / "empty.txt", "")
    _write(dataset_root / "images" / "val" / "empty.png", "fake image")

    sample = raw_root / "sample_eventlab_filter"
    sample.mkdir(parents=True)
    _write(sample / "image.png", "fake image")
    _write(
        sample / "metadata.json",
        json.dumps(
            {
                "image": "image.png",
                "window": {"width": 1280, "height": 720},
                "understanding": {"screen": "eventlab_filter", "active_tab": "", "selected_item": "收藏"},
                "candidates": [{"label": "modal_warning", "bbox": [0.2, 0.2, 0.8, 0.8]}],
            },
            ensure_ascii=False,
        ),
    )

    report = audit_dataset(
        raw_root=raw_root,
        dataset_root=dataset_root,
        class_targets={"race_result": 3, "post_race_next": 2},
        screen_targets={"eventlab_filter": 2, "race_pause_menu": 1},
    )

    race_result = next(item for item in report["class_gaps"] if item["name"] == "race_result")
    eventlab_filter = next(item for item in report["screen_gaps"] if item["screen"] == "eventlab_filter")

    assert race_result["count"] == 1
    assert race_result["deficit"] == 2
    assert eventlab_filter["count"] == 1
    assert eventlab_filter["deficit"] == 1
    assert report["yolo"]["empty_label_files"] == 1
    assert report["yolo"]["missing_images"] == 0
    assert any(item["priority"] == "critical" for item in report["next_collection"])


def test_dataset_audit_markdown_contains_collection_plan(tmp_path):
    report = audit_dataset(
        raw_root=tmp_path / "missing_raw",
        dataset_root=tmp_path / "missing_yolo",
        class_targets={"race_result": 1},
        screen_targets={"eventlab_filter": 1},
    )

    markdown = render_markdown(report)

    assert "优先补采" in markdown
    assert "`race_result`" in markdown
    assert "`eventlab_filter`" in markdown


def test_data_yaml_uses_relative_dataset_path_when_called_with_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dataset_root = tmp_path / "datasets" / "forza_ui" / "yolo"
    dataset_root.mkdir(parents=True)

    _write_data_yaml(dataset_root.relative_to(tmp_path))

    assert (dataset_root / "data.yaml").read_text(encoding="utf-8").splitlines()[0] == "path: datasets/forza_ui/yolo"
