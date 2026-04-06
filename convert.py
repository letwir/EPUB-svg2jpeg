#!/usr/bin/env python3
"""convert.py

プロトタイプ: EPUB内の cover.xhtml に埋め込まれた inline <svg> をラスタ化して
`item/images/cover.jpeg` として保存、opfを修正する。

簡易実装でエラーハンドリングはスキップして次へ進む方針（YOUKEN に準拠）。
"""

import argparse
import io
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import cairosvg
from lxml import etree
from PIL import Image, ImageOps


def extract_epub(epub_path, dest_dir):
    with ZipFile(epub_path, "r") as z:
        z.extractall(dest_dir)


def write_epub(src_dir, out_path):
    # EPUB requires mimetype as first entry, uncompressed
    mimetype_path = os.path.join(src_dir, "mimetype")
    with ZipFile(out_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as z:
        if os.path.isfile(mimetype_path):
            z.writestr(
                "mimetype", open(mimetype_path, "rb").read(), compress_type=ZIP_STORED
            )
        for root, _, files in os.walk(src_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src_dir)
                if rel == "mimetype":
                    continue
                z.write(full, rel, compress_type=ZIP_DEFLATED, compresslevel=9)


def rasterize_svg_string(svg_text, width, height, font_spec=None, font_is_url=False):
    # font_spec handling:
    # - if font_is_url is True, font_spec is treated as a relative URL to reference in @font-face (e.g. ../fonts/NotoSans.ttf)
    # - otherwise, font_spec is treated as a font-family name to apply (system font)
    font_size = 24
    style_block = ""
    if font_spec:
        if font_is_url:
            font_family = "EmbeddedFont"
            style_block = (
                f"<style>@font-face{{font-size:{font_size}pt; font-family:'{font_family}'; src: url('{font_spec}') format('truetype');}} "
                f"svg{{font-size:{font_size}pt; font-family:'{font_family}', sans-serif;}}</style>"
            )
        else:
            font_family = font_spec
            style_block = f"<style>svg{{font-size:{font_size}pt; font-family:'{font_family}', sans-serif;}}</style>"

    # Use regex-based injection of viewport attributes to avoid XML parse errors
    s = (
        svg_text
        if isinstance(svg_text, str)
        else svg_text.decode("utf-8", errors="ignore")
    )
    # detect existing attributes in opening <svg ...>
    m = re.search(r"<svg\b([^>]*)>", s, flags=re.IGNORECASE)
    if m:
        attrs = m.group(1)
        has_width = bool(re.search(r'\bwidth\s*=\s*"?\w+', attrs, flags=re.IGNORECASE))
        has_height = bool(
            re.search(r'\bheight\s*=\s*"?\w+', attrs, flags=re.IGNORECASE)
        )
        has_viewbox = bool(
            re.search(r"\bviewBox\s*=|\bviewbox\s*=", attrs, flags=re.IGNORECASE)
        )
        if not (has_width and has_height) and not has_viewbox:
            s = re.sub(
                r"(<svg\b)([^>]*)>",
                r"\1\2 width=\"%d\" height=\"%d\" viewBox=\"0 0 %d %d\">"
                % (width, height, width, height),
                s,
                count=1,
                flags=re.IGNORECASE,
            )

    # inject style block (font embedding or family) immediately after opening <svg>
    if style_block:
        s = re.sub(
            r"(<svg\b[^>]*>)", r"\1" + style_block, s, count=1, flags=re.IGNORECASE
        )

    try:
        png_bytes = cairosvg.svg2png(bytestring=s.encode("utf-8"))
    except Exception as e:
        # final fallback: try forcing size injection again (more aggressive)
        try:
            s2 = re.sub(
                r"(<svg\b)([^>]*)>",
                r"\1\2 width=\"%d\" height=\"%d\" viewBox=\"0 0 %d %d\">"
                % (width, height, width, height),
                s,
                count=1,
                flags=re.IGNORECASE,
            )
            png_bytes = cairosvg.svg2png(bytestring=s2.encode("utf-8"))
        except Exception:
            raise
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # Fit to target canvas while preserving aspect ratio and center
    target = (width, height)
    fitted = ImageOps.fit(img, target, method=Image.LANCZOS, centering=(0.5, 0.5))
    out = Image.new("RGB", target, (255, 255, 255))
    out.paste(fitted, (0, 0), fitted if fitted.mode == "RGBA" else None)
    return out


def insert_cover(
    tree: etree._ElementTree,
    cover_href="images/cover.jpeg",
    cover_id: str = "cover",
    cover_media_type="image/jpeg",
    area="manifest",
    child="item",
):
    manifests = tree.xpath(f'//*[local-name()="{area}"]')
    if manifests:
        manifest = manifests[0]
        items = manifest.xpath(f'*[local-name()="{child}"]')
        cover_found = False
        for item in items:
            href = (item.get("href") or "").strip()
            # detect existing cover reference or candidate cover entries
            if href.lower().endswith(cover_href):
                cover_found = True
        # if no cover item exists, insert one at the beginning of manifest
        if not cover_found:
            # preserve namespace if present
            manifest_tag = manifest.tag
            if "}" in manifest_tag:
                ns = manifest_tag[1 : manifest_tag.find("}")]
                item_tag = f"{{{ns}}}item"
            else:
                item_tag = "item"
            new_item = etree.Element(item_tag)
            new_item.set("media-type", cover_media_type)
            new_item.set("id", cover_id)
            new_item.set("href", cover_href)
            manifest.insert(0, new_item)
    return tree


def process_single_epub(epub_path, out_path, timeout, font_spec=None):
    base_name = os.path.basename(epub_path)
    tmp = tempfile.mkdtemp(prefix="epubproc_")
    status = "NG"
    try:
        extract_epub(epub_path, tmp)

        # locate cover.xhtml under item/xhtml/cover.xhtml (common pattern)
        cover_rel = os.path.join("item", "xhtml", "cover.xhtml")
        cover_path = os.path.join(tmp, cover_rel)
        images_dir = os.path.join(tmp, "item", "images")
        os.makedirs(images_dir, exist_ok=True)

        out_img_path = os.path.join(images_dir, "cover.jpeg")
        # If cover image already exists in EPUB, skip processing for this EPUB
        if os.path.isfile(out_img_path):
            # write output epub as-is (will include existing image)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            write_epub(tmp, out_path)
            status = "OK skip"
            print(f"input: {epub_path}, output: {out_path}, status: {status}")
            shutil.rmtree(tmp, ignore_errors=True)
            return

        # prepare font: if user provided a TTF path, copy it into EPUB tmp dir and use relative URL
        font_for_svg = None
        font_is_url = False
        copied_font_path = None
        if font_spec:
            if os.path.isfile(font_spec):
                fonts_dir = os.path.join(tmp, "item", "fonts")
                os.makedirs(fonts_dir, exist_ok=True)
                basefont = os.path.basename(font_spec)
                dest_font = os.path.join(fonts_dir, basefont)
                try:
                    shutil.copy(font_spec, dest_font)
                    # relative path from cover.xhtml (item/xhtml) to fonts is ../fonts/<file>
                    font_for_svg = "../fonts/" + basefont
                    font_is_url = True
                    copied_font_path = dest_font
                except Exception:
                    font_for_svg = font_spec
                    font_is_url = False
            else:
                font_for_svg = font_spec
                font_is_url = False

        if os.path.isfile(cover_path):
            # cover.xhtml may be malformed XML; use regex to extract first <svg>...</svg> block
            with open(cover_path, "r", encoding="utf-8", errors="ignore") as f:
                cover_text = f.read()

            m = re.search(
                r"<svg\b.*?</svg>", cover_text, flags=re.DOTALL | re.IGNORECASE
            )
            if m:
                svg_string = m.group(0)
                img = rasterize_svg_string(
                    svg_string,
                    width=1600,
                    height=2560,
                    font_spec=font_for_svg,
                    font_is_url=font_is_url,
                )
                out_img_path = os.path.join(images_dir, "cover.jpeg")
                img.save(
                    out_img_path,
                    format="JPEG",
                    quality=100,
                    subsampling=0,
                    optimize=True,
                    progressive=False,
                )

                # remove copied font file only (do not remove fonts directory)
                if copied_font_path and os.path.isfile(copied_font_path):
                    try:
                        os.remove(copied_font_path)
                    except Exception:
                        pass

                # --- Update OPF manifest to point to new JPEG cover ---
                try:
                    # find first .opf file in extracted EPUB
                    opf_path = None
                    for r, ds, fs in os.walk(tmp):
                        for fn in fs:
                            if fn.lower().endswith(".opf"):
                                opf_path = os.path.join(r, fn)
                                break
                        if opf_path:
                            break

                    if opf_path and os.path.isfile(opf_path):
                        try:
                            parser = etree.XMLParser(
                                ns_clean=True, recover=True, encoding="utf-8"
                            )
                            tree = etree.parse(opf_path, parser)
                            # find manifest element robustly
                            tree = insert_cover(
                                tree,
                                cover_href="images/cover.jpeg",
                                cover_id="cover",
                                cover_media_type="image/jpeg",
                                area="manifest",
                                child="item",
                            )
                            tree = insert_cover(
                                tree,
                                cover_href="images/cover.jpeg",
                                cover_id="cover",
                                cover_media_type="image/jpeg",
                                area="spine",
                                child="itemref",
                            )
                            # write back opf
                            tree.write(opf_path, encoding="utf-8", xml_declaration=True)
                        except Exception:
                            pass
                except Exception:
                    pass

        # write output epub
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        write_epub(tmp, out_path)
        status = "OK"
    except Exception as e:
        status = f"NG: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"input: {epub_path}, output: {out_path}, status: {status}")


def find_epubs(input_path):
    if os.path.isfile(input_path) and input_path.lower().endswith(".epub"):
        return [input_path]
    matches = []
    for root, dirs, files in os.walk(input_path):
        for f in files:
            if f.lower().endswith(".epub"):
                matches.append(os.path.join(root, f))
    return matches


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("-j", "--jobs", type=int, default=1)
    p.add_argument(
        "-f",
        "--font",
        default="/usr/share/fonts/opentype/noto/NotoSansCJK-Bold",
        help="Path to TTF file or font family name (default: %(default)s)",
    )
    p.add_argument("-t", "--timeout", type=int, default=300)
    args = p.parse_args()

    epubs = find_epubs(args.input)
    tasks = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futures = []
        for epub in epubs:
            out_name = os.path.basename(epub)
            out_path = args.output
            if os.path.isdir(args.output):
                out_path = os.path.join(args.output, out_name)
            futures.append(
                ex.submit(process_single_epub, epub, out_path, args.timeout, args.font)
            )

        for f in as_completed(futures):
            pass


if __name__ == "__main__":
    main()
