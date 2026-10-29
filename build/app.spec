# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（产出 macOS .app）—— 对应 app/main.py（PyQt6 图标整理工具）
#
# 需要改的只有下面这几个常量。
import os

_here = SPECPATH  # spec 文件所在目录（PyInstaller 注入）

ENTRY = os.path.join(_here, "..", "app", "main.py")
APP_NAME = "IconStudio"                     # 产物名（.app 文件名），保持纯 ASCII 最省心
BUNDLE_ID = "com.local.iconstudio"          # 反向域名唯一标识
DISPLAY_NAME = "主题图标批量处理"             # Dock / 菜单栏里显示的名字

_icon = os.path.join(_here, "..", "resources", "icon.icns")
ICON = _icon if os.path.exists(_icon) else None  # 由 build/make_icns.py 生成

a = Analysis(
    [ENTRY],
    pathex=[os.path.join(_here, "..", "app")],
    binaries=[],
    # 需要随包分发的数据文件写在这里，例：[("../resources/data.json", "data")]
    datas=[],
    # PyQt6 有官方 hook，一般不用手动补；只有动态 import 的模块才需要
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # ← GUI 程序必须是 False，否则会多一个终端窗口
    argv_emulation=False,
    target_arch=None,  # None = 跟随构建机架构
    codesign_identity=None,
    entitlements_file=os.path.join(_here, "entitlements.plist"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=APP_NAME + ".app",
    icon=ICON,
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleName": DISPLAY_NAME,
        "CFBundleDisplayName": DISPLAY_NAME,
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSPrincipalClass": "NSApplication",
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSRequiresAquaSystemAppearance": False,
        # 允许在 Finder 里「用本应用打开」文件夹
        "CFBundleDocumentTypes": [],
        "NSHumanReadableCopyright": "",
    },
)
