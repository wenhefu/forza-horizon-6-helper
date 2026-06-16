# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

datas = []
binaries = []
hiddenimports = []

for package in ("rapidocr_onnxruntime", "numpy", "PIL", "cv2", "yaml", "vgamepad"):
    try:
        tmp_ret = collect_all(package)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

try:
    binaries += collect_dynamic_libs("onnxruntime")
    datas += collect_data_files(
        "onnxruntime",
        excludes=[
            "**/quantization/**",
            "**/tools/**",
            "**/transformers/**",
            "**/test/**",
            "**/tests/**",
        ],
    )
    hiddenimports += ["onnxruntime.capi.onnxruntime_pybind11_state"]
except Exception:
    pass

# The GUI imports runners lazily inside worker threads, and mode3_runner imports the V5
# nav lazily -- PyInstaller can't follow those, so list the whole stack explicitly.
hiddenimports += [
    "v4.mode3_runner",
    "v4.farm_runner",
    "v4.recognizer",
    "v4.decision",
    "v4.sell_runner",      # 清理重复22B button (lazy import in gui_v4)
    "v4.sell_planner",
    "v4.auction_runner",   # 拍卖场抢车 button (lazy import in gui_v4)
    "v4.unowned_buyer",    # 买未拥有的车 button (lazy import in gui_v4)
    "v4.unowned_surveyor", # 统计未拥有的车 button (lazy import in gui_v4)
    "v5.nav_runner",       # V5 event-driven nav toggle (lazy import in mode3_runner)
    "v5.reactor",
    "v5.screen_registry",
    "v5.capture_engine",   # dxcam imported lazily inside -> no dxcam bundle needed
    "v3.buying_ui",        # skill-point / sell / auction detectors
    "buy_car_runner",
    "smart_runner",
    "single_instance",
    "driver_check",
]

datas += [
    ("v3/models", "v3/models"),
    ("README_V4.md", "."),
    ("README_VISION.md", "."),
]


a = Analysis(
    ["v4_gui_launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "ultralytics",
        "matplotlib",
        "scipy",
        "sympy",
        "polars",
        "requests",
        "fsspec",
        "jinja2",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Forza6HelperV4GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
