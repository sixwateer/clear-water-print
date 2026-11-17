# -*- coding: utf-8 -*-
"""把「HTML 普通版」同步到 docs/index.html，供 GitHub Pages 部署。

用法（在任意目录执行均可）：
    python "02_HTML版/发布到Pages.py"

为什么需要这一步：
    GitHub Pages 只把站点根目录的 index.html 当作首页，而交付文件叫
    「净像去水印_普通版_双击即用.html」。docs/index.html 是部署用副本，
    源文件永远是 02_HTML版/净像去水印_普通版_双击即用.html。

改完 HTML 后必须跑一次本脚本再提交，否则线上还是旧版本。
"""
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # 02_HTML版
ROOT = HERE.parent                               # 项目根目录
SRC = HERE / "净像去水印_普通版_双击即用.html"
DST = ROOT / "docs" / "index.html"


def sha8(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def main() -> int:
    if not SRC.exists():
        print(f"[失败] 找不到源文件：{SRC}")
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    before = sha8(DST) if DST.exists() else None
    shutil.copyfile(SRC, DST)
    after = sha8(DST)

    size_kb = DST.stat().st_size / 1024
    if before == after:
        print(f"[已是最新] docs/index.html 与源文件一致（sha {after}，{size_kb:.0f} KB）")
    else:
        print(f"[已同步] {SRC.name} → docs/index.html")
        print(f"         {size_kb:.0f} KB，sha {before or '（新建）'} → {after}")

    print("         部署地址：https://sixwateer.github.io/clear-water-print/")
    print("         提交推送到 main 后约 1 分钟生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
