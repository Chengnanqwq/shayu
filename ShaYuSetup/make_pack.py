"""把一个目录打成插件市场能装的数据包（zip），并打印要贴进 index.json 的条目。

用法：
    python make_pack.py --src "D:/表情包" --id emotes-bluefish --name "蓝色大肥鱼表情包
" \
        --target emotes --out "D:/packs" --url "http://example.com/packs/emotes-bluefish.zip"

产物：
    <out>/<id>-<version>.zip
    屏幕上打印的 JSON（粘到 index.json 的 plugins 数组里，type 是 data）
"""
import argparse
import hashlib
import json
import pathlib
import sys
import zipfile

EXTS = (".gif", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".bmp")


def human(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f}GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f}MB"
    return f"{n / 1024:.0f}KB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="要打包的目录")
    ap.add_argument("--id", required=True, help="条目 id（英文数字横线）")
    ap.add_argument("--name", required=True, help="显示名")
    ap.add_argument("--version", default="1.0.0")
    ap.add_argument("--target", default="emotes", help="装到安装目录下的哪个子目录，默认 emotes")
    ap.add_argument("--out", default="packs", help="zip 输出目录")
    ap.add_argument("--url", default="", help="别人下载这个 zip 的地址（http(s) 或 /packs/xxx.zip）")
    ap.add_argument("--desc", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--tags", default="表情")
    a = ap.parse_args()

    src = pathlib.Path(a.src)
    if not src.is_dir():
        print("找不到目录:", src)
        return 1
    files = [p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in EXTS]
    if not files:
        print("目录里没有可打包的图/视频（支持 " + " ".join(EXTS) + "）")
        return 1

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    zp = out / f"{a.id}-{a.version}.zip"
    total = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in files:
            arc = f.relative_to(src).as_posix()
            z.write(f, arc)
            total += f.stat().st_size
    size = zp.stat().st_size
    sha = hashlib.sha256(zp.read_bytes()).hexdigest()[:16]

    entry = {
        "type": "data",
        "id": a.id,
        "name": a.name,
        "version": a.version,
        "author": a.author or "匿名",
        "desc": a.desc or f"{len(files)} 个文件，装到 {a.target}/",
        "tags": [t.strip() for t in a.tags.split(",") if t.strip()],
        "target": a.target,
        "files": len(files),
        "size": size,
        "sha256": sha,
        "url": a.url or f"/packs/{zp.name}",
    }
    print(f"\n打包完成：{zp}")
    print(f"  {len(files)} 个文件，原始 {human(total)}，压缩后 {human(size)}")
    print("\n把这个条目放进 index.json 的 plugins 数组里：\n")
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    print("\n提示：")
    print("  · url 写 /packs/xxx.zip 表示由机器人自己托管：把 zip 放到 <安装目录>/packs/ 即可")
    print("  · 想让别人也能装，就把 url 换成公网地址（GitHub Release / 你自己的服务器）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
