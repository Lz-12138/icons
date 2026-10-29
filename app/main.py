# -*- coding: utf-8 -*-
"""
华为/荣耀主题图标批量整理工具（GUI + 命令行，单文件）
====================================================

功能
----
1. 扫描“完整图标787个PNG”文件夹中的全部 PNG：
   - 第三方应用（中文名/英文名/ic_launcher_*）→ 改为官方 Android 包名；
   - 华为/荣耀系统应用（拨号、会员中心、设置等）→ 改为 EMUI / HarmonyOS 4
     官方包名；
   - 已经是包名格式的文件默认保持不变。
2. 支持“一个源图标 → 多个输出名”：
   - RENAME_MAP / SUGGESTIONS 的值统一写成列表；
   - 列表里的每个名字都会生成一张同名 PNG（同一张原图，尺寸/画质完全一致）。
3. 把每张图重绘到 192×192 画布：
   - 先按透明通道裁出图标实际内容；
   - 中心内容缩放到画布的 60%（192 × 0.6 = 115px）；
   - 画布保持 192×192 透明背景，图标居中；
   - 使用 LANCZOS + 预乘 Alpha 缩放，PNG 无损保存（optimize + 最高压缩）。
4. 输出到新文件夹（默认“输出_192x192”），原图不动，并按类型分文件夹：
   - 第三方应用 → 第三方02-04/
   - 华为/荣耀系统必画图标 → 华为必画/
   - 三个指定例外 → 荣耀/
   同时生成完整报告和“未识别图标清单.csv”（只列没有查到映射、保留原名的源图标）。
5. 自带 PyQt6 图形界面（现代深色风格）：
   - 可选择输入/输出文件夹；
   - 可设置画布大小（默认 192×192）和中心元素缩放比例（默认 60%）；
   - 实时进度与日志，完成后可直接打开输出目录。

用法
----
    python icon_de.py                   # 无参数 → 启动 GUI
    python icon_de.py --gui             # 启动 GUI
    python icon_de.py --dry-run         # 命令行：只分析，不写图片
    python icon_de.py --force           # 命令行：输出目录非空时先清空再处理
    python icon_de.py --no-suggestions  # 命令行：不应用 SUGGESTIONS，只保留原名并列入清单
    python icon_de.py --src "D:/图标" --out "D:/图标_192"
    python icon_de.py --canvas 192 --scale 0.6

依赖：Pillow、PyQt6（pip install pillow pyqt6）

说明
----
- 包名以 EMUI / HarmonyOS 4 为准；HarmonyOS NEXT 的包名不同
  （如 com.ohos.contacts、com.huawei.hmos.*），本脚本不混用。
- 不同 EMUI 版本的系统包名可能略有差异，RENAME_MAP 可直接增删修改。
- 一个源图标要输出多个名字时，把值写成列表即可，例如：
      "录音机": ["com.android.soundrecorder", "com.huawei.soundrecorder"],
- SUGGESTIONS 是补充映射，默认也会应用，并在报告里标记“按建议重命名”；
  不想应用时加 --no-suggestions。
- “未识别图标清单”只包含没有查到映射、保留原名的源图标；
  建议映射、重名跳过、输出名冲突不再进入该清单。
- 输出名与原文件夹里已有的 PNG 重名时，跳过该源图，保留原图；
  其余输出名冲突仍按“显式映射 > 建议映射 > 保留包名”处理。
- 分类规则在 classify_output() 中，可直接增删 MUST_DRAW_* / THIRD_PARTY_NAMES。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# 打包成窗口程序（console=False）后没有控制台，stdout/stderr 可能是 None，
# 这时任何 print 都会抛异常；先兜一个黑洞流。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Windows 控制台默认 GBK，强制 UTF-8 避免中文打印报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = Path(__file__).resolve().parent

# 打包成 .app / .exe 后 __file__ 位于应用包内部（macOS 上在只读位置），
# 默认目录不能落在那里，否则既选不中文件夹也写不出结果。
if getattr(sys, "frozen", False):
    DATA_ROOT = Path.home() / "Documents"
else:
    DATA_ROOT = BASE_DIR

DEFAULT_SRC = DATA_ROOT / "完整图标787个PNG"
DEFAULT_OUT = DATA_ROOT / "输出_192x192"
DEFAULT_CANVAS = 192
DEFAULT_SCALE = 0.60

# 已经是包名格式：至少包含一个点，允许下划线（含 _fg 后缀）
PKG_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")

# Windows 文件名非法字符
INVALID_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---------------------------------------------------------------------------
# 输出分类：第三方 / 华为必画 / 荣耀
# ---------------------------------------------------------------------------
THIRD_PARTY_DIR = "第三方02-04"
MUST_DRAW_DIR = "华为必画"
HONOR_DIR = "荣耀"
OUTPUT_DIRS = (THIRD_PARTY_DIR, MUST_DRAW_DIR, HONOR_DIR)

# 用户指定的三个例外，单独放“荣耀”
HONOR_EXCEPTIONS = {
    "com.hihonor.assistant",
    "com.hihonor.auto",
    "com.hihonor.collectcenter",
}

# 华为/荣耀系统应用，以及华为自家云服务、商城
MUST_DRAW_PREFIXES = (
    "com.huawei.",
    "com.hihonor.",
    "app.huawei.",
    "com.hicloud.",
    "com.vmall.",
)

# com.android.* 中属于系统应用的包名；
# 其余 com.android.*（Chrome、Play、银行/股票等）按第三方处理。
MUST_DRAW_ANDROID = {
    "com.android.browser",
    "com.android.calculator2",
    "com.android.calendar",
    "com.android.camera.packet.CameraPacketActivity",
    "com.android.contacts",
    "com.android.contacts.activities.DialtactsActivity",
    "com.android.deskclock",
    "com.android.email",
    "com.android.gallery3d",
    "com.android.hwmirror",
    "com.android.mms",
    "com.android.settings",
    "com.android.soundrecorder",
    "com.android.stk",
    "com.android.stk.StkLauncherActivity",
    "com.android.stk.StkLauncherActivity2",
    "com.android.updater",
}

# 非包名的系统资源/系统图标
MUST_DRAW_NAMES = {
    "wifi",
    "蓝牙",
    "流量",
    "游戏中心vivo",
    "动态日历预览",
    "动态时钟预览",
    "荣耀商城",
    "新闻资讯",
    "安卓",
    "远程守护",
    "短视频",
    "ic_launcher_videoeditor",
}

# 明确属于第三方/其他品牌的非包名图标
THIRD_PARTY_NAMES = {
    "tachyon",
    "ic_launcher_bbs",
    "ic_launcher_musiclink",
}


def classify_output(out_name: str) -> str:
    """判断输出图标应放入哪个文件夹。"""
    if out_name in HONOR_EXCEPTIONS:
        return HONOR_DIR
    if out_name in THIRD_PARTY_NAMES:
        return THIRD_PARTY_DIR
    if out_name.startswith(MUST_DRAW_PREFIXES):
        return MUST_DRAW_DIR
    if out_name in MUST_DRAW_ANDROID or out_name in MUST_DRAW_NAMES:
        return MUST_DRAW_DIR
    if out_name.startswith("status_bar_toggle_"):
        return MUST_DRAW_DIR
    if out_name.startswith("ic_") and not out_name.startswith("ic_launcher_"):
        return MUST_DRAW_DIR
    return THIRD_PARTY_DIR


# ---------------------------------------------------------------------------
# 重命名映射表
# ---------------------------------------------------------------------------
# 说明：
#   - 左侧是原 PNG 文件名（不含 .png）；
#   - 右侧是“输出名列表”，列表里有几个名字就生成几张同名 PNG；
#   - 已经是包名格式、且不在此表中的文件，脚本原样保留。
RENAME_MAP: dict[str, list[str]] = {
    # ===== 第三方应用 =====
    "AR-zone": ["com.samsung.android.arzone"],
    "Googlemeet": ["com.google.android.apps.meetings"],
    "Keep": ["com.gotokeep.keep"],
    "Messenger": ["com.facebook.orca"],
    "MicrosoftTeams": ["com.microsoft.teams"],
    "Paytm": ["net.one97.paytm"],
    "QQ": ["com.tencent.mobileqq"],
    "facebook": ["com.facebook.katana"],
    "gmail": ["com.google.android.gm"],
    "google game": ["com.google.android.play.games"],
    "google setting": ["com.google.android.gms"],
    "google云盘": ["com.google.android.apps.docs"],
    "google文件夹": ["com.google.android.documentsui"],
    "line": ["jp.naver.line.android"],
    "photos": ["com.google.android.apps.photos"],
    "saavn": ["com.saavn.android"],
    "spotify": ["com.spotify.music"],
    "talk": ["com.google.android.talk"],
    "tinder": ["com.tinder"],
    "vending": ["com.android.vending"],
    "viber": ["com.viber.voip"],
    "whatsapp": ["com.whatsapp"],
    "youtube": ["com.google.android.youtube"],
    "今日头条": ["com.ss.android.article.news"],
    "微博": ["com.sina.weibo"],
    "快手": ["com.smile.gifmaker"],
    "快手极速版": ["com.kuaishou.nebula"],
    "抖音": ["com.ss.android.ugc.aweme"],
    "拼多多": ["com.xunmeng.pinduoduo"],
    "搜狐视频": ["com.sohu.sohuvideo"],
    "支付宝": ["com.eg.android.AlipayGphone"],
    "爱奇艺": ["com.qiyi.video"],
    "饿了么": ["me.ele"],
    "金铲铲之战": ["com.tencent.jkchess"],
    "亚马逊": ["com.amazon.mShop.android.shopping"],
    "千问": ["com.aliyun.tongyi"],
    "小米商城": ["com.xiaomi.shop"],
    "小米账户": ["com.xiaomi.account"],
    "oppo社区": ["com.oppo.community"],
    "vivo空间": ["com.vivo.space"],
    "中国移动": ["com.greenpoint.android.mc10086.activity"],
    "ic_launcher_douban_frodo": ["com.douban.frodo"],
    "ic_launcher_oneplus_bbs": ["com.oneplus.bbs"],
    "stk1": ["com.android.stk", "com.android.stk.StkLauncherActivity"],
    # ===== 华为/荣耀系统应用（可一项对多名）=====
    "一键锁屏": ["com.huawei.hwonekeylock"],
    "主题商店": ["com.huawei.android.thememanager"],
    "云服务": ["com.huawei.hicloud"],
    "会员中心": ["com.huawei.mycenter"],
    "我的华为": ["com.huawei.myhuawei"],
    "客户服务": ["com.huawei.phoneservice"],
    "应用商店": ["com.huawei.appmarket"],
    "应用抽屉": ["com.huawei.android.launcher"],
    "录音机": ["com.android.soundrecorder", "com.huawei.soundrecorder"],
    "扫一扫": ["com.huawei.scanner"],
    "指南针": ["com.huawei.compass"],
    "收音机": ["com.huawei.android.FMRadio"],
    "文件管理": ["com.huawei.hidisk"],
    "日历": ["com.android.calendar", "com.huawei.calendar"],
    "时钟": ["com.android.deskclock", "com.huawei.deskclock"],
    "智慧生活": ["com.huawei.smarthome"],
    "查找手机": ["com.huawei.android.findmyphone"],
    "桌面搜索": ["com.huawei.search"],
    "测量": ["com.huawei.ar.measure"],
    "浏览器": ["com.android.browser", "com.huawei.browser"],
    "游戏中心": ["com.huawei.gamebox.global", "com.huawei.gamebox", "com.huawei.gamecenter"],
    "游戏空间": ["com.oplus.play"],
    "玩机技巧": ["com.huawei.android.tips"],
    "生活服务": ["com.huawei.lives"],
    "电子邮件": ["com.android.email", "com.huawei.email"],
    "相册": ["com.android.gallery3d", "com.huawei.photos"],
    "相机": ["com.huawei.camera"],
    "短信": ["com.android.mms"],
    "穿戴": ["com.huawei.bone"],
    "联系人": ["com.android.contacts", "com.huawei.contacts"],
    # 拨号与联系人同属 com.android.contacts，用桌面 Activity 名区分
    "拨号": ["com.android.contacts.activities.DialtactsActivity"],
    "视频": ["com.huawei.himovie", "com.huawei.himovie.overseas"],
    "计算器": ["com.android.calculator2", "com.huawei.calculator"],
    "设置": ["com.android.settings"],
    "语音助手": ["com.huawei.vassistant"],
    "钱包": ["com.huawei.wallet"],
    "镜子": ["com.huawei.mirror", "com.android.hwmirror"],
    "阅读": ["com.huawei.hnreader"],
    "com.huawei.hwireader": ["com.huawei.hwread.al", "com.huawei.hwireader"],
    "音乐": ["com.huawei.music"],
    "驾驶模式": ["com.huawei.vdrive"],
    "天气": ["com.huawei.android.totemweather", "com.huawei.android.totemweatherapp"],
    "天际通": ["com.huawei.hiskytone"],
    "安全中心": ["com.huawei.systemmanager"],
    "备份": ["com.huawei.KoBackup"],
    "商城": ["com.vmall.client"],
    "华为地图": ["com.hihonor.auto"],
    "小游戏": ["游戏中心vivo"],
    "手电筒": ["com.huawei.flashlight"],
    "遥控器": ["com.huawei.android.remotecontroller"],
    "未成年模式": ["com.huawei.parentcontrol"],
    "便签": ["com.huawei.notepad", "com.example.android.notepad"],
    "健康": ["com.huawei.health"],
    "卓易通": ["com.droi.tong"],
    # ===== 荣耀系统应用 =====
    "荣耀健康": ["com.hihonor.health"],
    "荣耀商城": ["荣耀商城"],
    "荣耀应用商店": ["com.hihonor.appmarket"],
    "我的荣耀": ["com.hihonor.phoneservice"],
    "反馈中心": ["com.hihonor.collectcenter"],
}

# 补充映射：默认应用，并在报告中标记“按建议重命名”。
# 加 --no-suggestions 后不应用，只保留原名并列入未识别清单。
SUGGESTIONS: dict[str, list[str]] = {
    "手写笔": ["com.huawei.stylus.mpenzone"],
    "下载": ["com.huawei.filemanager"],
    # "新闻资讯": ["com.huawei.intelligent"],   # 不存在
    # "远程守护": ["com.hihonor.parentcontrol"],
    "使用手册": ["com.huawei.tipsove"],
    "电子书": ["com.huawei.hwread.dznew"],
    # "流量": ["com.huawei.netassistant"],      # oppo
    "礼品": ["com.huawei.honorclub.android"],
    "交互池": ["com.huawei.accountagent"],
    "动态日历预览": ["动态日历预览"],
    "动态时钟预览": ["动态时钟预览"],
    # "安卓": ["无对应独立应用"],               # 不存在
    "温度计": ["com.huawei.thermometer"],
    # "短视频": ["com.hihonor.video"],
    "stk2": ["com.android.stk.StkLauncherActivity2"],
    # "tachyon": ["未知应用"],
    # "ic_launcher_bbs": ["com.hicloud.android.clone"],
    "ic_launcher_encryptiont": ["ic_onekey_widget_preview", "ic_onekey_widget_shortcut"],
    # "ic_launcher_musiclink": ["未知应用"],    # oppo
    "ic_launcher_ohome": ["ic_flashlight_preview", "ic_flashlight_shortcut"],
    "ic_launcher_shortcuts": ["com.hicloud.android.clone"],
    # "ic_launcher_videoeditor": ["com.huawei.educenter"],
}


@dataclass
class Row:
    src_name: str          # 原文件名（不含扩展名）
    out_name: str          # 输出文件名（不含扩展名）
    status: str            # 状态
    note: str = ""         # 说明 / 建议
    priority: int = 0      # 冲突时优先级：映射 > 建议 > 保留包名 > 未识别
    produce: bool = True   # 是否实际生成这张图
    review: bool = False   # 是否列入“待人工确认”清单


def is_package_name(stem: str) -> bool:
    """判断文件名是否已经是包名格式。"""
    return PKG_RE.fullmatch(stem) is not None


def is_valid_output_name(name: str) -> bool:
    """输出名必须是当前系统可用的文件名。"""
    if not name or name in {".", ".."}:
        return False
    return INVALID_NAME_RE.search(name) is None


def _dedupe(items: list[str]) -> list[str]:
    """去重并保持原顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def build_plan(
    stems: list[str],
    apply_suggestions: bool = True,
) -> tuple[list[Row], dict[str, list[str]]]:
    """生成逐个输出文件的计划，并解决输出名冲突。

    返回：
      - rows：每行对应一个“源文件 → 输出名”，包含冲突/错误的行；
      - outputs_by_src：每个源文件最终要生成的输出名列表（可能 1 个或多个）。
    """
    rows: list[Row] = []

    for stem in sorted(stems):
        targets: list[str]
        note = ""
        priority: int
        status: str
        review = False

        if stem in RENAME_MAP:
            targets = RENAME_MAP[stem]
            priority = 3
            status = "重命名"
            if len(targets) > 1:
                note = f"1→{len(targets)}：同一图标同时输出多个名字"
        elif apply_suggestions and stem in SUGGESTIONS:
            targets = SUGGESTIONS[stem]
            priority = 2
            status = "按建议重命名"
            note = "按建议映射"
            if len(targets) > 1:
                note += f"；1→{len(targets)}"
        elif is_package_name(stem):
            targets = [stem]
            priority = 1
            status = "保留（已是包名）"
        else:
            targets = [stem]
            priority = 0
            status = "未识别：保留原名"
            review = True
            if stem in SUGGESTIONS:
                note = "建议：" + "、".join(SUGGESTIONS[stem]) + "（未应用）"

        targets = _dedupe(targets)

        for target in targets:
            if not is_valid_output_name(target):
                rows.append(Row(
                    stem, target, "错误：输出名非法",
                    "包含文件名不允许的字符，已跳过",
                    priority, produce=False, review=review,
                ))
                continue

            # 映射值与原文件名相同：实际是“保留原名”
            if target == stem and status in ("重命名", "按建议重命名"):
                row_status = "保留原名（建议）" if status == "按建议重命名" else "保留原名"
                row_note = "映射值与原名相同"
                if status == "按建议重命名":
                    row_note += "；按建议映射"
            else:
                row_status = status
                row_note = note

            rows.append(Row(
                stem, target, row_status, row_note,
                priority, produce=True, review=review,
            ))

    # 输出名与原文件夹里已有的 PNG 重名：跳过改名，保留原图
    source_set = set(stems)
    for row in rows:
        if (
            row.produce
            and row.src_name != row.out_name
            and row.out_name in source_set
        ):
            row.produce = False
            row.status = "跳过：与原图重名"
            row.note = f"原文件夹已有 {row.out_name}.png，保留原图"

    # 其余输出名冲突：同一输出名只保留一张图，按优先级决定由哪个源图生成
    groups: dict[str, list[Row]] = {}
    for row in rows:
        if row.produce:
            groups.setdefault(row.out_name, []).append(row)

    winners: dict[str, Row] = {}
    for out_name, group in groups.items():
        # 优先级高者胜；同优先级时“源名 == 输出名”优先；再按源名排序
        best = sorted(
            group,
            key=lambda r: (
                -r.priority,
                0 if r.src_name == r.out_name else 1,
                r.src_name,
            ),
        )[0]
        winners[out_name] = best
        for row in group:
            if row is best:
                continue
            row.produce = False
            row.status = "冲突：输出名已被占用"
            row.note = f"由 {best.src_name}.png 生成；本图跳过"

    outputs_by_src: dict[str, list[str]] = {}
    for out_name, row in winners.items():
        outputs_by_src.setdefault(row.src_name, []).append(out_name)
    for outs in outputs_by_src.values():
        outs.sort()

    return rows, outputs_by_src


def _render_on_canvas(im: Image.Image, target: int, canvas: int) -> Image.Image:
    """把 im 等比缩到最长边约 target，然后居中贴到透明画布上。"""
    w, h = im.size
    factor = target / max(w, h)
    nw = max(1, round(w * factor))
    nh = max(1, round(h * factor))

    if (nw, nh) != (w, h):
        # RGBa 为预乘 Alpha 模式，缩小时边缘不会出现黑边
        im = im.convert("RGBa").resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA")

    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(im, ((canvas - nw) // 2, (canvas - nh) // 2), im)
    return out


def resize_icon(src: Path, dsts: list[Path], canvas: int, scale: float) -> None:
    """裁出透明内容 → 缩放为画布的 scale → 居中放到 canvas×canvas 画布。

    同一个源图标要输出多个名字时，只解码/缩放一次，其余文件直接复制，
    保证所有输出图完全一致。

    LANCZOS 会把裁剪边界最外 1px 的 Alpha 衰减到 0，所以按可见区域
    反算一次，确保最终可见内容正好是 canvas×scale（192×0.6 = 115px）。
    """
    if not dsts:
        return

    with Image.open(src) as im:
        im.load()
        if im.mode != "RGBA":
            im = im.convert("RGBA")

        # 只保留图标实际可见区域；四周透明留白不参与 60% 计算
        bbox = im.getchannel("A").getbbox()
        if bbox:
            im = im.crop(bbox)

        desired = max(1, round(canvas * scale))
        target = desired
        out = _render_on_canvas(im, target, canvas)

        # 最多校正 2 次，使不透明内容的可见边长等于 desired
        for _ in range(2):
            bb = out.getchannel("A").getbbox()
            visible = max(bb[2] - bb[0], bb[3] - bb[1]) if bb else 0
            if visible == 0 or visible == desired:
                break
            target = max(1, target + (desired - visible))
            out = _render_on_canvas(im, target, canvas)

        # PNG 无损；optimize + 最高压缩，画质不损失
        out.save(dsts[0], format="PNG", optimize=True, compress_level=9)

    # 一对多：其余名字直接复制，避免重复缩放，也保证字节完全一致
    for dst in dsts[1:]:
        shutil.copyfile(dsts[0], dst)


def write_reports(out_dir: Path, rows: list[Row]) -> tuple[Path, Path]:
    """写出完整报告和未识别图标清单。"""
    report = out_dir / "重命名报告.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["原文件名", "输出文件名", "分类文件夹", "状态", "说明"])
        for r in rows:
            writer.writerow([
                f"{r.src_name}.png",
                f"{r.out_name}.png",
                classify_output(r.out_name),
                r.status,
                r.note,
            ])

    todo = out_dir / "未识别图标清单.csv"
    pending = [r for r in rows if r.review]
    with todo.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["原文件名", "输出文件名", "分类文件夹", "状态", "建议 / 说明"])
        for r in pending:
            writer.writerow([
                f"{r.src_name}.png",
                f"{r.out_name}.png",
                classify_output(r.out_name),
                r.status,
                r.note,
            ])

    return report, todo


def prepare_out_dir(out_dir: Path, src_dir: Path, force: bool, dry_run: bool) -> None:
    """检查/创建输出目录；非空时要求 --force。"""
    if dry_run:
        return
    if out_dir.resolve() == src_dir.resolve():
        raise SystemExit("输出目录不能与源目录相同。")

    if out_dir.exists():
        existing = list(out_dir.iterdir())
        if existing and not force:
            raise SystemExit(
                f"输出目录已存在且非空：{out_dir}\n"
                f"如需覆盖，请加 --force（会先清空其中的文件和子文件夹）。"
            )
        if force:
            for p in existing:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="华为/荣耀主题图标重命名 + 192×192（内容 60%）处理")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="源 PNG 文件夹")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出文件夹")
    parser.add_argument("--canvas", type=int, default=DEFAULT_CANVAS, help="画布边长，默认 192")
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE, help="中心内容占画布比例，默认 0.6")
    parser.add_argument("--dry-run", action="store_true", help="只分析并打印结果，不写图片")
    parser.add_argument("--force", action="store_true", help="输出目录非空时先清空")
    parser.add_argument(
        "--no-suggestions", action="store_true",
        help="不应用 SUGGESTIONS 中的待核对映射（默认会应用）",
    )
    args = parser.parse_args(argv)

    src_dir: Path = args.src
    out_dir: Path = args.out
    apply_suggestions = not args.no_suggestions

    if not src_dir.is_dir():
        print(f"[错误] 找不到源文件夹：{src_dir}")
        return 1
    if not (0 < args.scale <= 1):
        print("[错误] --scale 必须在 (0, 1] 之间")
        return 1
    if args.canvas <= 0:
        print("[错误] --canvas 必须大于 0")
        return 1

    pngs = sorted(
        p for p in src_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".png"
    )
    if not pngs:
        print(f"[错误] 源文件夹里没有 PNG：{src_dir}")
        return 1

    rows, outputs_by_src = build_plan([p.stem for p in pngs], apply_suggestions)

    produced_rows = [r for r in rows if r.produce]
    counts: dict[str, int] = Counter(r.status for r in produced_rows)

    multi = {s: outs for s, outs in outputs_by_src.items() if len(outs) > 1}
    extra_outputs = sum(len(outs) - 1 for outs in multi.values())

    print(f"源目录 : {src_dir}")
    print(f"输出目录: {out_dir}")
    print(f"源 PNG  : {len(pngs)}")
    print(f"输出 PNG: {len(produced_rows)}（一对多额外生成 {extra_outputs} 张）")
    print(f"画布尺寸: {args.canvas}×{args.canvas}，中心内容占比 {args.scale:.0%}")
    print(f"待核对映射（SUGGESTIONS）: {'应用' if apply_suggestions else '未应用'}")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {status}: {n}")

    folder_counts = Counter(
        classify_output(out_name)
        for outs in outputs_by_src.values()
        for out_name in outs
    )
    print("\n分类输出：")
    for folder in OUTPUT_DIRS:
        print(f"  {folder}: {folder_counts.get(folder, 0)}")

    if multi:
        print("\n一对多输出：")
        for src_name, outs in sorted(multi.items()):
            print(f"  {src_name}.png → " + "、".join(f"{o}.png" for o in outs))

    pending = [r for r in rows if r.review]
    if pending:
        print("\n未查询到映射的源图标（保留原名）：")
        for r in pending:
            hint = f"  {r.note}" if r.note else ""
            print(f"  - {r.src_name}.png{hint}")

    if args.dry_run:
        print("\n[dry-run] 未写入任何文件。")
        return 0

    prepare_out_dir(out_dir, src_dir, args.force, args.dry_run)

    for folder in OUTPUT_DIRS:
        (out_dir / folder).mkdir(parents=True, exist_ok=True)

    ok_sources = 0
    ok_files = 0
    skipped_sources: list[str] = []
    failed: list[tuple[str, str]] = []

    for i, src in enumerate(pngs, 1):
        outs = outputs_by_src.get(src.stem)
        if not outs:
            # 所有输出名都被别的源图占用，或映射值非法
            skipped_sources.append(src.name)
        else:
            dsts = [
                out_dir / classify_output(out_name) / f"{out_name}.png"
                for out_name in outs
            ]
            try:
                resize_icon(src, dsts, args.canvas, args.scale)
                ok_sources += 1
                ok_files += len(dsts)
            except Exception as exc:  # noqa: BLE001 - 单张失败不影响其余图片
                failed.append((src.name, str(exc)))
        if i % 50 == 0 or i == len(pngs):
            print(f"  处理进度 {i}/{len(pngs)}")

    report, todo = write_reports(out_dir, rows)

    print("\n完成：")
    print(f"  成功源图: {ok_sources}/{len(pngs)}，输出文件: {ok_files}")
    if skipped_sources:
        print(f"  跳过 {len(skipped_sources)} 个源图（与原图重名 / 输出名冲突）：")
        for name in skipped_sources:
            print(f"    - {name}")
    if failed:
        print(f"  失败: {len(failed)}")
        for name, err in failed[:10]:
            print(f"    - {name}: {err}")
    print(f"  完整报告: {report}")
    print(f"  未识别清单: {todo}")
    return 0 if not failed else 2

# ==================== GUI（PyQt6） ====================

import sys
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)



# ---------------------------------------------------------------------------
# 深色主题样式
# ---------------------------------------------------------------------------

# macOS 没有微软雅黑和 Consolas，换系统自带的苹方 / Menlo
_UI_FONT = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
_MONO_FONT = "Menlo" if sys.platform == "darwin" else "Consolas"

QSS = """
* {
    font-family: "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 10pt;
    color: #E6E9F0;
}
QMainWindow, QWidget#root {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #0B0D11, stop:1 #121722);
}
QDialog, QMessageBox {
    background: #141820;
}
QMessageBox QLabel {
    color: #E6E9F0;
    min-width: 280px;
}
QMessageBox QPushButton {
    min-width: 82px;
}
QFrame#card {
    background: #161A21;
    border: 1px solid #242B36;
    border-radius: 14px;
}
QFrame#accent {
    background: #5B7CFF;
    border-radius: 2px;
}
QLabel#title {
    font-size: 22px;
    font-weight: 700;
    color: #FFFFFF;
}
QLabel#subtitle {
    font-size: 9.5pt;
    color: #8B93A3;
}
QLabel#section {
    font-size: 9pt;
    font-weight: 700;
    color: #8FA6D8;
    letter-spacing: 1px;
}
QLabel#hint {
    font-size: 9pt;
    color: #7E8797;
}
QLabel#badge {
    background: #1A2233;
    color: #8FA6FF;
    border: 1px solid #2B3A5C;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 8.5pt;
    font-weight: 700;
}
QLabel#status {
    font-size: 10pt;
    font-weight: 600;
    color: #8B93A3;
}
QLineEdit, QSpinBox {
    background: #0F1218;
    border: 1px solid #2A3140;
    border-radius: 9px;
    padding: 9px 12px;
    selection-background-color: #5B7CFF;
    selection-color: #FFFFFF;
}
QLineEdit:hover, QSpinBox:hover {
    border-color: #394456;
}
QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #5B7CFF;
    background: #10141B;
}
QLineEdit:disabled, QSpinBox:disabled {
    color: #626A79;
    background: #12151B;
    border-color: #222833;
}
QPushButton {
    background: #202631;
    border: 1px solid #2C3442;
    border-radius: 9px;
    padding: 9px 16px;
    color: #DCE1EA;
}
QPushButton:hover {
    background: #273040;
    border-color: #3A4557;
}
QPushButton:pressed {
    background: #1B212B;
}
QPushButton:disabled {
    color: #5E6675;
    background: #171B22;
    border-color: #232A35;
}
QPushButton#primary {
    background: #5B7CFF;
    border: 1px solid #5B7CFF;
    color: #FFFFFF;
    font-weight: 700;
    padding: 11px 26px;
}
QPushButton#primary:hover {
    background: #6D8BFF;
    border-color: #6D8BFF;
}
QPushButton#primary:pressed {
    background: #4B6BEA;
}
QPushButton#primary:disabled {
    background: #2B3550;
    border-color: #2B3550;
    color: #7C879E;
}
QPushButton#ghost {
    background: transparent;
    border: 1px solid #2C3442;
}
QPushButton#ghost:hover {
    background: #1D232D;
}
QPushButton#danger {
    background: #2A1B20;
    border: 1px solid #4A2A33;
    color: #FF9AA8;
}
QPushButton#danger:hover {
    background: #362129;
    border-color: #64323F;
}
QPushButton#danger:disabled {
    background: #171B22;
    border-color: #232A35;
    color: #5E6675;
}
QPushButton#small {
    padding: 5px 12px;
    font-size: 9pt;
}
QCheckBox {
    color: #C9CFDA;
    spacing: 9px;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid #394252;
    background: #0F1218;
}
QCheckBox::indicator:hover {
    border-color: #5B7CFF;
}
QCheckBox::indicator:checked {
    background: #5B7CFF;
    border-color: #5B7CFF;
}
QProgressBar {
    background: #0F1218;
    border: 1px solid #242B36;
    border-radius: 8px;
    height: 16px;
    text-align: center;
    color: #AAB2C2;
    font-size: 8.5pt;
}
QProgressBar::chunk {
    background: #5B7CFF;
    border-radius: 7px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #262D3A;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #5B7CFF;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: #FFFFFF;
    border: 2px solid #5B7CFF;
}
QSlider::handle:horizontal:hover {
    border-color: #8FA6FF;
}
QPlainTextEdit {
    background: #0B0D11;
    border: 1px solid #242B36;
    border-radius: 10px;
    padding: 10px;
    color: #B8C0CE;
    selection-background-color: #5B7CFF;
    selection-color: #FFFFFF;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #2E3746;
    min-height: 30px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #3B4658;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QToolTip {
    background: #1C222C;
    color: #E6E9F0;
    border: 1px solid #2C3442;
    padding: 6px 8px;
}
"""


def section_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


class IconWorker(QThread):
    """后台处理线程：读取图标 → 建立计划 → 缩放 → 写报告。"""

    progress = pyqtSignal(int, int, str)   # 当前, 总数, 当前文件名
    log = pyqtSignal(str)
    done = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(
        self,
        src_dir: Path,
        out_dir: Path,
        canvas: int,
        scale: float,
        apply_suggestions: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.src_dir = src_dir
        self.out_dir = out_dir
        self.canvas = canvas
        self.scale = scale
        self.apply_suggestions = apply_suggestions
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: C901 - 流程清晰，单函数便于阅读
        try:
            pngs = sorted(
                p for p in self.src_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".png"
            )
            if not pngs:
                raise RuntimeError(f"源文件夹里没有 PNG：{self.src_dir}")

            self.log.emit(f"源 PNG：{len(pngs)}")
            rows, outputs_by_src = build_plan(
                [p.stem for p in pngs], self.apply_suggestions
            )
            produced_rows = [r for r in rows if r.produce]
            multi = {s: v for s, v in outputs_by_src.items() if len(v) > 1}
            extra = sum(len(v) - 1 for v in multi.values())

            self.log.emit(f"计划输出：{len(produced_rows)} 张（一对多额外 {extra} 张）")
            planned_folders = Counter(
                classify_output(r.out_name) for r in produced_rows
            )
            self.log.emit(
                "分类："
                + " / ".join(
                    f"{name} {planned_folders.get(name, 0)}"
                    for name in OUTPUT_DIRS
                )
            )

            skipped = [p.name for p in pngs if not outputs_by_src.get(p.stem)]
            if skipped:
                self.log.emit(f"跳过 {len(skipped)} 个源图：{'、'.join(skipped)}")

            for folder in OUTPUT_DIRS:
                (self.out_dir / folder).mkdir(parents=True, exist_ok=True)

            actual_folders: Counter[str] = Counter()
            ok_sources = 0
            ok_files = 0
            failed: list[tuple[str, str]] = []
            cancelled = False
            total = len(pngs)

            for i, src in enumerate(pngs, 1):
                if self._cancel:
                    cancelled = True
                    self.log.emit("收到停止请求，已停止后续处理。")
                    break

                outs = outputs_by_src.get(src.stem)
                if outs:
                    dsts = [
                        self.out_dir
                        / classify_output(out_name)
                        / f"{out_name}.png"
                        for out_name in outs
                    ]
                    try:
                        resize_icon(src, dsts, self.canvas, self.scale)
                        ok_sources += 1
                        ok_files += len(dsts)
                        for out_name in outs:
                            actual_folders[classify_output(out_name)] += 1
                    except Exception as exc:  # noqa: BLE001 - 单张失败不中断
                        failed.append((src.name, str(exc)))
                        self.log.emit(f"失败：{src.name} — {exc}")

                self.progress.emit(i, total, src.name)
                if i % 50 == 0 or i == total:
                    self.log.emit(f"处理进度 {i}/{total}")

            report, todo = write_reports(self.out_dir, rows)

            self.done.emit({
                "sources": len(pngs),
                "outputs": ok_files,
                "ok_sources": ok_sources,
                "skipped": len(skipped),
                "failed": len(failed),
                "folders": {
                    name: actual_folders.get(name, 0)
                    for name in OUTPUT_DIRS
                },
                "report": str(report),
                "todo": str(todo),
                "cancelled": cancelled,
            })
        except Exception:
            self.error.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker: IconWorker | None = None
        self._out_manual = False

        self.setWindowTitle("主题图标批量处理 · Icon Studio")
        self.resize(960, 860)
        self.setMinimumSize(860, 720)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(26, 24, 26, 22)
        main.setSpacing(15)

        main.addLayout(self._build_header())
        main.addWidget(self._build_paths_card())
        main.addWidget(self._build_params_card())
        main.addLayout(self._build_actions())
        main.addLayout(self._build_progress())
        main.addWidget(self._build_log_card(), 1)

        self._load_defaults()
        self._append_log("就绪。选择输入文件夹后点击“开始处理”。")

    # ------------------------------------------------------------------ UI
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        accent = QFrame()
        accent.setObjectName("accent")
        accent.setFixedSize(4, 46)
        row.addWidget(accent)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel("主题图标批量处理")
        title.setObjectName("title")
        subtitle = QLabel("重命名 · 画布缩放 · 自动分类 · 无损 PNG")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        row.addLayout(title_box)
        row.addStretch()

        badge = QLabel("DARK UI")
        badge.setObjectName("badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(badge)
        return row

    def _build_paths_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 17, 20, 20)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        grid.addWidget(section_label("文件夹"), 0, 0, 1, 3)

        grid.addWidget(QLabel("输入文件夹"), 1, 0)
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("选择包含 PNG 图标的文件夹")
        self.src_edit.setClearButtonEnabled(True)
        grid.addWidget(self.src_edit, 1, 1)
        self.src_btn = QPushButton("浏览…")
        self.src_btn.setFixedWidth(88)
        grid.addWidget(self.src_btn, 1, 2)

        grid.addWidget(QLabel("输出文件夹"), 2, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("默认在输入文件夹旁创建 输出_192x192")
        self.out_edit.setClearButtonEnabled(True)
        grid.addWidget(self.out_edit, 2, 1)
        self.out_btn = QPushButton("浏览…")
        self.out_btn.setFixedWidth(88)
        grid.addWidget(self.out_btn, 2, 2)

        grid.setColumnStretch(1, 1)

        self.src_btn.clicked.connect(self._choose_src)
        self.out_btn.clicked.connect(self._choose_out)
        self.src_edit.editingFinished.connect(self._sync_output_from_src)
        self.src_edit.textEdited.connect(self._on_src_typed)
        self.out_edit.textEdited.connect(self._on_out_typed)
        self.out_edit.textChanged.connect(self._update_open_button)

        for btn in (self.src_btn, self.out_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return card

    def _build_params_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 17, 20, 20)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        grid.addWidget(section_label("处理参数"), 0, 0, 1, 4)

        grid.addWidget(QLabel("画布尺寸"), 1, 0)
        self.canvas_spin = QSpinBox()
        self.canvas_spin.setRange(16, 2048)
        self.canvas_spin.setValue(DEFAULT_CANVAS)
        self.canvas_spin.setSuffix(" px")
        self.canvas_spin.setFixedWidth(118)
        self.canvas_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        grid.addWidget(self.canvas_spin, 1, 1)
        self.canvas_hint = QLabel("正方形画布，默认 192 × 192")
        self.canvas_hint.setObjectName("hint")
        grid.addWidget(self.canvas_hint, 1, 2, 1, 2)

        grid.addWidget(QLabel("中心元素缩放"), 2, 0)
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 100)
        self.scale_slider.setValue(round(DEFAULT_SCALE * 100))
        self.scale_slider.setPageStep(5)
        grid.addWidget(self.scale_slider, 2, 1)

        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(10, 100)
        self.scale_spin.setValue(round(DEFAULT_SCALE * 100))
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setFixedWidth(92)
        self.scale_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scale_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        grid.addWidget(self.scale_spin, 2, 2)

        self.scale_hint = QLabel()
        self.scale_hint.setObjectName("hint")
        self.scale_hint.setMinimumWidth(150)
        grid.addWidget(self.scale_hint, 2, 3)

        options = QWidget()
        opt_row = QHBoxLayout(options)
        opt_row.setContentsMargins(0, 4, 0, 0)
        opt_row.setSpacing(24)
        self.suggest_check = QCheckBox("应用建议映射（SUGGESTIONS）")
        self.suggest_check.setChecked(True)
        self.suggest_check.setToolTip(
            "勾选后，SUGGESTIONS 中待核对的包名也会应用；\n"
            "报告中会标记为“按建议重命名”。"
        )
        self.force_check = QCheckBox("清空并覆盖输出文件夹")
        self.force_check.setChecked(False)
        self.force_check.setToolTip(
            "输出文件夹非空时，默认会弹窗确认；\n"
            "勾选后直接清空，不再询问。"
        )
        opt_row.addWidget(self.suggest_check)
        opt_row.addWidget(self.force_check)
        opt_row.addStretch()
        grid.addWidget(options, 3, 0, 1, 4)

        grid.setColumnStretch(1, 1)

        self.scale_slider.valueChanged.connect(self.scale_spin.setValue)
        self.scale_spin.valueChanged.connect(self.scale_slider.setValue)
        self.scale_slider.valueChanged.connect(self._update_scale_hint)
        self.canvas_spin.valueChanged.connect(self._update_scale_hint)
        self._update_scale_hint()

        for cb in (self.suggest_check, self.force_check):
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
        return card

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.start_btn = QPushButton("开始处理")
        self.start_btn.setObjectName("primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self.start_processing)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop_processing)

        self.open_btn = QPushButton("打开输出文件夹")
        self.open_btn.setObjectName("ghost")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_output)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("status")

        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.open_btn)
        row.addStretch()
        row.addWidget(self.status_label)
        return row

    def _build_progress(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("等待开始")
        box.addWidget(self.progress)

        self.file_label = QLabel("")
        self.file_label.setObjectName("hint")
        self.file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        box.addWidget(self.file_label)
        return box

    def _build_log_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(section_label("运行日志"))
        head.addStretch()
        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("small")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(lambda: self.log_edit.clear())
        head.addWidget(clear_btn)
        box.addLayout(head)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("处理日志会显示在这里…")
        self.log_edit.setMaximumBlockCount(3000)
        self.log_edit.setFont(QFont(_MONO_FONT, 9))
        self.log_edit.setMinimumHeight(180)
        box.addWidget(self.log_edit, 1)
        return card

    # -------------------------------------------------------------- defaults
    def _load_defaults(self) -> None:
        if DEFAULT_SRC.is_dir():
            self.src_edit.setText(str(DEFAULT_SRC))
        self.out_edit.setText(str(DEFAULT_OUT))
        self._out_manual = False
        self.open_btn.setEnabled(DEFAULT_OUT.exists())
        self._update_scale_hint()

    def _update_scale_hint(self) -> None:
        canvas = self.canvas_spin.value()
        percent = self.scale_spin.value()
        desired = max(1, round(canvas * percent / 100))
        self.scale_hint.setText(f"可见内容约 {desired}px（{percent}%）")
        self.canvas_hint.setText(f"正方形画布，当前 {canvas} × {canvas}")

    # ---------------------------------------------------------------- paths
    def _on_src_typed(self, _text: str) -> None:
        # 手动改输入路径时，输出路径仍然自动跟随（除非用户手动改过输出）
        self._sync_output_from_src()

    def _on_out_typed(self, _text: str) -> None:
        self._out_manual = True

    def _sync_output_from_src(self) -> None:
        if self._out_manual:
            return
        text = self.src_edit.text().strip()
        if not text:
            return
        src = Path(text)
        self.out_edit.setText(str(src.parent / "输出_192x192"))

    def _choose_src(self) -> None:
        start = self.src_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择输入文件夹", start)
        if chosen:
            self.src_edit.setText(chosen)
            self._sync_output_from_src()

    def _choose_out(self) -> None:
        start = self.out_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择输出文件夹", start)
        if chosen:
            self.out_edit.setText(chosen)
            self._out_manual = True

    # ------------------------------------------------------------- run state
    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.start_btn.setText("处理中…" if running else "开始处理")
        self.stop_btn.setEnabled(running)
        self.open_btn.setEnabled(not running and self._current_out_exists())

        for w in (
            self.src_edit, self.src_btn, self.out_edit, self.out_btn,
            self.canvas_spin, self.scale_slider, self.scale_spin,
            self.suggest_check, self.force_check,
        ):
            w.setEnabled(not running)

    def _current_out_exists(self) -> bool:
        text = self.out_edit.text().strip()
        return bool(text) and Path(text).is_dir()

    def _update_open_button(self) -> None:
        if self.worker is None:
            self.open_btn.setEnabled(self._current_out_exists())

    # ------------------------------------------------------------------ log
    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{stamp}] {message}")
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ---------------------------------------------------------------- start
    def start_processing(self) -> None:
        if self.worker is not None:
            return

        if not self._out_manual:
            self._sync_output_from_src()

        src_text = self.src_edit.text().strip()
        out_text = self.out_edit.text().strip()
        if not src_text:
            QMessageBox.warning(self, "缺少输入", "请先选择输入文件夹。")
            return
        if not out_text:
            QMessageBox.warning(self, "缺少输出", "请先选择输出文件夹。")
            return

        src_dir = Path(src_text)
        out_dir = Path(out_text)
        if not src_dir.is_dir():
            QMessageBox.critical(self, "输入无效", f"找不到输入文件夹：\n{src_dir}")
            return
        try:
            has_png = any(
                p.is_file() and p.suffix.lower() == ".png"
                for p in src_dir.iterdir()
            )
        except OSError as exc:
            QMessageBox.critical(self, "读取失败", str(exc))
            return
        if not has_png:
            QMessageBox.warning(
                self, "没有 PNG", f"输入文件夹里没有 PNG 文件：\n{src_dir}"
            )
            return

        if out_dir.exists() and not out_dir.is_dir():
            QMessageBox.critical(
                self, "输出无效", f"输出路径已存在但不是文件夹：\n{out_dir}"
            )
            return
        if out_dir.resolve() == src_dir.resolve():
            QMessageBox.critical(
                self, "输出无效", "输出文件夹不能与输入文件夹相同。"
            )
            return

        if out_dir.exists() and any(out_dir.iterdir()):
            if not self.force_check.isChecked():
                reply = QMessageBox.question(
                    self,
                    "输出文件夹非空",
                    f"输出文件夹已存在且非空：\n{out_dir}\n\n"
                    "是否清空其中的文件和子文件夹并覆盖？",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        try:
            # force=True：调用前已经确认过，或用户勾选了“清空并覆盖”
            prepare_out_dir(out_dir, src_dir, force=True, dry_run=False)
        except SystemExit as exc:
            QMessageBox.critical(self, "无法使用输出目录", str(exc))
            return
        except OSError as exc:
            QMessageBox.critical(
                self, "无法清空输出目录", f"{out_dir}\n\n{exc}"
            )
            return

        canvas = self.canvas_spin.value()
        percent = self.scale_spin.value()
        scale = percent / 100.0

        self.start_btn.setEnabled(False)
        self._set_running(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("准备中…")
        self.file_label.setText("正在读取源文件夹…")
        self.status_label.setText("处理中…")
        self.status_label.setStyleSheet("color: #8FA6FF;")
        self.log_edit.clear()
        self._append_log("开始处理")
        self._append_log(f"输入：{src_dir}")
        self._append_log(f"输出：{out_dir}")
        self._append_log(f"画布：{canvas}×{canvas}，中心元素：{percent}%")
        self._append_log(
            "SUGGESTIONS：" + ("应用" if self.suggest_check.isChecked() else "不应用")
        )

        self.worker = IconWorker(
            src_dir=src_dir,
            out_dir=out_dir,
            canvas=canvas,
            scale=scale,
            apply_suggestions=self.suggest_check.isChecked(),
            parent=self,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._append_log)
        self.worker.done.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def stop_processing(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.stop_btn.setEnabled(False)
            self.status_label.setText("正在停止…")
            self.status_label.setStyleSheet("color: #F0B36A;")
            self._append_log("正在停止…")

    # --------------------------------------------------------------- signals
    def _on_progress(self, current: int, total: int, name: str) -> None:
        if self.progress.maximum() != total:
            self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.progress.setFormat(f"{current} / {total}")
        self.file_label.setText(f"正在处理：{name}")

    def _on_done(self, summary: dict) -> None:
        self._set_running(False)
        self.file_label.setText("")
        self.progress.setValue(self.progress.maximum())

        if summary.get("cancelled"):
            self.progress.setFormat("已停止")
            self.status_label.setText("已停止")
            self.status_label.setStyleSheet("color: #F0B36A;")
            self._append_log("已停止，当前输出为部分结果。")
        else:
            self.progress.setFormat("完成")
            self.status_label.setText("完成")
            self.status_label.setStyleSheet("color: #7EE2A8;")
            self._append_log(
                f"完成：{summary['sources']} 个源图 → {summary['outputs']} 张"
            )

        for folder in OUTPUT_DIRS:
            self._append_log(f"  {folder}: {summary['folders'].get(folder, 0)}")
        if summary.get("skipped"):
            self._append_log(
                f"  跳过 {summary['skipped']} 个源图（与原图重名 / 输出名冲突）"
            )
        if summary.get("failed"):
            self._append_log(f"  失败 {summary['failed']} 个源图，详见上方日志。")
            QMessageBox.warning(
                self,
                "部分图标未处理",
                f"有 {summary['failed']} 个源图处理失败，"
                "详情请查看运行日志。",
            )
        self._append_log(f"报告：{summary['report']}")
        self._append_log(f"未识别清单：{summary['todo']}")

    def _on_error(self, detail: str) -> None:
        self._set_running(False)
        self.progress.setFormat("失败")
        self.status_label.setText("失败")
        self.status_label.setStyleSheet("color: #FF6B6B;")
        self.file_label.setText("")
        self._append_log("处理失败：")
        for line in detail.rstrip().splitlines():
            self._append_log(f"  {line}")
        QMessageBox.critical(
            self,
            "处理失败",
            detail.rstrip().splitlines()[-1] if detail.strip() else "未知错误",
        )

    def _on_worker_finished(self) -> None:
        self.worker = None

    # ---------------------------------------------------------------- misc
    def open_output(self) -> None:
        text = self.out_edit.text().strip()
        if not text:
            return
        out_dir = Path(text)
        if not out_dir.is_dir():
            QMessageBox.information(self, "提示", "输出文件夹还不存在。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self.worker is not None and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "正在处理",
                "图标仍在处理中，确定停止并退出吗？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
            if not self.worker.wait(5000):
                self.worker.terminate()
                self.worker.wait(1000)
        event.accept()


def run_gui() -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("IconStudio")
    app.setApplicationDisplayName("主题图标批量处理")
    app.setStyle("Fusion")
    app.setFont(QFont(_UI_FONT, 10))
    app.setStyleSheet(QSS)

    window = MainWindow()
    window.show()
    # macOS 上从 Finder 启动时窗口可能留在后面，主动提到前台
    window.raise_()
    window.activateWindow()
    return app.exec()


def main() -> int:
    """无参数或带 --gui 时启动界面，其余参数走命令行模式。"""
    argv = sys.argv[1:]
    if not argv or "--gui" in argv:
        return run_gui()
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
