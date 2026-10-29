#!/usr/bin/env python3
"""把 app/1.ico 转成 resources/icon.icns —— 构建时自动调用（build-macos.sh 里）。

macOS 的 `iconutil` 只能在 Mac 上用，但 .icns 本身是公开容器格式：

    'icns' + 大端总长度 + 若干 (4 字节类型 + 大端长度 + PNG 数据)

PNG 型条目自 macOS 10.7 起支持，Finder / Dock / 应用切换器都能正常显示。
这样 Windows 上也能预先验证结构，macOS 上构建时自动生成，仓库里不必存二进制。
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "1.ico"
DST = ROOT / "resources" / "icon.icns"

# (类型, 像素) —— 现代 ic07~ic14 + 老式 icp4~icp6 全给上，兼容性最好
ENTRIES = [
    ("icp4", 16),
    ("icp5", 32),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),
    ("ic11", 32),   # 16@2x
    ("ic12", 64),   # 32@2x
    ("ic13", 256),  # 128@2x
    ("ic14", 512),  # 256@2x
]


def build_icns(src: Path) -> bytes:
    master = Image.open(src).convert("RGBA")
    print(f"  源图标：{src.name} {master.size[0]}x{master.size[1]}")

    blocks = []
    for kind, size in ENTRIES:
        img = master.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        blocks.append((kind, buf.getvalue()))

    body = b"".join(k.encode("ascii") + struct.pack(">I", len(p) + 8) + p for k, p in blocks)
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def verify_icns(payload: bytes) -> None:
    """回读校验：文件头、总长度、每个条目长度是否自洽。"""
    assert payload[:4] == b"icns", "icns 魔数错误"
    total = struct.unpack(">I", payload[4:8])[0]
    assert total == len(payload), f"总长度不一致：{total} != {len(payload)}"

    pos, found = 8, []
    while pos < total:
        kind = payload[pos:pos + 4].decode("ascii")
        length = struct.unpack(">I", payload[pos + 4:pos + 8])[0]
        assert length >= 8, f"{kind} 长度非法"
        data = payload[pos + 8:pos + length]
        assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{kind} 不是 PNG"
        found.append(kind)
        pos += length

    assert pos == total, "条目长度累加与总长度不符"
    # PIL 也能作为独立实现回读一次
    im = Image.open(io.BytesIO(payload))
    print(f"  校验通过：{len(found)} 个尺寸 {found}，PIL 回读 {im.size[0]}x{im.size[1]}")


def main() -> int:
    if not SRC.exists():
        print(f"  ⚠️ 没有 {SRC}，跳过图标生成（将使用默认图标）")
        return 0
    if DST.exists() and "--force" not in sys.argv:
        print(f"  已存在 {DST.name}，跳过（加 --force 强制重建）")
        return 0

    payload = build_icns(SRC)
    verify_icns(payload)
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_bytes(payload)
    print(f"  ✅ {DST.relative_to(ROOT)} ({len(payload) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
