from __future__ import annotations

import argparse
import math
from pathlib import Path

import easyocr
import numpy as np
import pypdfium2 as pdfium
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from PIL import Image

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pdf"}


class HandwritingToExcelConverter:
    def __init__(self, languages: list[str], gpu: bool = False) -> None:
        self.reader = easyocr.Reader(languages, gpu=gpu)

    def convert(self, input_path: Path, output_path: Path, confidence_threshold: float = 0.2) -> None:
        pages = self._load_pages(input_path)
        workbook = Workbook()
        default_sheet = workbook.active
        workbook.remove(default_sheet)

        for index, page_image in enumerate(pages, start=1):
            sheet = workbook.create_sheet(title=f"Page_{index}")
            self._write_page_to_sheet(page_image, sheet, confidence_threshold)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)

    def _load_pages(self, input_path: Path) -> list[Image.Image]:
        ext = input_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支援的檔案格式：{ext}")

        if ext == ".pdf":
            return self._render_pdf_pages(input_path)

        return [Image.open(input_path).convert("RGB")]

    def _render_pdf_pages(self, pdf_path: Path) -> list[Image.Image]:
        pdf = pdfium.PdfDocument(str(pdf_path))
        pages: list[Image.Image] = []

        for index in range(len(pdf)):
            page = pdf.get_page(index)
            bitmap = page.render(scale=220 / 72)
            pil_image = bitmap.to_pil().convert("RGB")
            pages.append(pil_image)
            page.close()

        pdf.close()
        return pages

    def _write_page_to_sheet(self, image: Image.Image, sheet, confidence_threshold: float) -> None:
        image_array = np.array(image)
        height, width = image_array.shape[:2]

        results = self.reader.readtext(
            image_array,
            detail=1,
            paragraph=False,
            text_threshold=0.5,
            low_text=0.2,
            width_ths=0.7,
        )

        filtered_results = [item for item in results if item[2] >= confidence_threshold and item[1].strip()]
        if not filtered_results:
            return

        row_count = min(max(int(height / 45), 20), 220)
        col_count = min(max(int(width / 90), 12), 120)

        row_height_pixels = height / row_count
        col_width_pixels = width / col_count

        for row in range(1, row_count + 1):
            sheet.row_dimensions[row].height = 18

        for col in range(1, col_count + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 12

        for bbox, text, confidence in filtered_results:
            xs = [point[0] for point in bbox]
            ys = [point[1] for point in bbox]

            x_min, x_max = max(min(xs), 0), min(max(xs), width)
            y_min, y_max = max(min(ys), 0), min(max(ys), height)

            start_col = max(1, min(col_count, int(x_min / col_width_pixels) + 1))
            end_col = max(1, min(col_count, int(math.ceil(x_max / col_width_pixels))))
            start_row = max(1, min(row_count, int(y_min / row_height_pixels) + 1))
            end_row = max(1, min(row_count, int(math.ceil(y_max / row_height_pixels))))

            cell = sheet.cell(row=start_row, column=start_col, value=text)
            cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
            cell.font = Font(size=11)

            if end_row > start_row or end_col > start_col:
                try:
                    sheet.merge_cells(
                        start_row=start_row,
                        start_column=start_col,
                        end_row=end_row,
                        end_column=end_col,
                    )
                except ValueError:
                    pass

            confidence_percent = round(confidence * 100, 1)
            cell.number_format = "@"
            cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
            cell.font = Font(size=11)
            if confidence_percent < 40:
                cell.font = Font(size=11, color="FF7F50")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="中文手寫 OCR：輸入圖片或 PDF，輸出 Excel，並盡量維持版面。"
    )
    parser.add_argument("input", type=Path, help="輸入檔案（圖片或 PDF）")
    parser.add_argument("output", type=Path, help="輸出的 Excel 檔案路徑（.xlsx）")
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["ch_tra", "en"],
        help="EasyOCR 語言代碼，預設為繁中+英文",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="若環境有可用 CUDA，開啟 GPU 推論",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.2,
        help="過濾低信心文字，範圍建議 0.1~0.6",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.output.suffix.lower() != ".xlsx":
        raise ValueError("輸出檔案必須是 .xlsx")

    converter = HandwritingToExcelConverter(languages=args.languages, gpu=args.gpu)
    converter.convert(
        input_path=args.input,
        output_path=args.output,
        confidence_threshold=args.confidence_threshold,
    )
    print(f"轉換完成：{args.output}")


if __name__ == "__main__":
    main()
