import io
import json
import math
import re
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.file.file import File
from PIL import Image, ImageOps, UnidentifiedImageError


class TileImagesTool(Tool):
    """Offline, layout-agnostic image tiler."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        images = tool_parameters.get("images")
        rows = self._as_int(tool_parameters.get("rows", 3), "rows")
        columns = self._as_int(tool_parameters.get("columns", 3), "columns")
        overlap = self._as_float(tool_parameters.get("overlap_ratio", 0.15), "overlap_ratio")
        quality = self._as_int(tool_parameters.get("jpeg_quality", 90), "jpeg_quality")
        include_overview = self._as_bool(tool_parameters.get("include_overview", True), "include_overview")

        if not isinstance(images, list) or not images:
            raise ValueError("images must be a non-empty Array[File].")
        if rows < 1 or columns < 1:
            raise ValueError("rows and columns must both be at least 1.")
        if not 0 <= overlap < 0.5:
            raise ValueError("overlap_ratio must be at least 0 and less than 0.5.")
        if not 1 <= quality <= 100:
            raise ValueError("jpeg_quality must be an integer from 1 through 100.")

        pages: list[dict[str, Any]] = []
        output_names: list[str] = []
        for file in images:
            page, payloads = self._process_one(file, rows, columns, overlap, include_overview, quality)
            pages.append(page)
            for filename, blob in payloads:
                if not blob:
                    raise RuntimeError(f"Generated a zero-byte file: {filename}")
                output_names.append(filename)
                yield self.create_blob_message(
                    blob=blob,
                    meta={"mime_type": "image/jpeg", "filename": filename},
                )

        expected = len(images) * (rows * columns + (1 if include_overview else 0))
        manifest_names = [
            name
            for page in pages
            for name in ([page["overviewFileName"]] if "overviewFileName" in page else [])
            + [tile["fileName"] for tile in page["tiles"]]
        ]
        if len(output_names) != expected or output_names != manifest_names:
            raise RuntimeError("Output file order/count does not match the tile manifest.")
        if len(output_names) != len(set(output_names)):
            raise RuntimeError("Output file names are not unique.")

        manifest = {"schemaVersion": "drawingTiles/v1", "pages": pages}
        yield self.create_text_message(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        for page in pages:
            # Multiple JSON messages become Dify's fixed json: Array[Object] output.
            yield self.create_json_message(page)

    def _process_one(
        self,
        file: Any,
        rows: int,
        columns: int,
        overlap: float,
        include_overview: bool,
        quality: int,
    ) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
        if not isinstance(file, File):
            raise ValueError("Each images item must be a Dify File.")

        filename = getattr(file, "filename", None) or "image.jpg"
        mime_type = (getattr(file, "mime_type", "") or "").lower()
        if mime_type not in {"image/jpeg", "image/jpg", "image/png"}:
            raise ValueError(f"Only JPEG and PNG are supported: {filename}")
        try:
            image = Image.open(io.BytesIO(file.blob))
            image.load()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError(f"Unable to decode image {filename}: {exc}") from exc
        if (image.format or "").upper() not in {"JPEG", "PNG"}:
            raise ValueError(f"Decoded image format is not JPEG or PNG: {filename}")

        image = ImageOps.exif_transpose(image)
        width, height = image.size
        if width < 1 or height < 1:
            raise ValueError(f"Invalid image dimensions for {filename}.")

        prefix, source_file_name, page_no = self._source_identity(filename)
        payloads: list[tuple[str, bytes]] = []
        page: dict[str, Any] = {
            "sourceImageFileName": filename,
            "sourceFileName": source_file_name,
            "sourcePageNo": page_no,
            "width": width,
            "height": height,
            "contentClassification": "unknown",
            "tiles": [],
        }
        if include_overview:
            overview_name = f"{prefix}_overview.jpg"
            payloads.append((overview_name, self._encode_jpeg(image, quality)))
            page["overviewFileName"] = overview_name

        x_boxes = self._expanded_axis_boxes(width, columns, overlap)
        y_boxes = self._expanded_axis_boxes(height, rows, overlap)
        for row, (top, bottom) in enumerate(y_boxes, start=1):
            for column, (left, right) in enumerate(x_boxes, start=1):
                tile_name = f"{prefix}_r{row}_c{column}.jpg"
                payloads.append((tile_name, self._encode_jpeg(image.crop((left, top, right, bottom)), quality)))
                page["tiles"].append(
                    {
                        "tileId": f"{self._document_stem(prefix)}::P{page_no}::R{row}C{column}",
                        "fileName": tile_name,
                        "row": row,
                        "column": column,
                        "pixelBox": {"left": left, "top": top, "right": right, "bottom": bottom},
                        "normalizedBox": {
                            "left": round(left / width, 8),
                            "top": round(top / height, 8),
                            "right": round(right / width, 8),
                            "bottom": round(bottom / height, 8),
                        },
                    }
                )
        return page, payloads

    @staticmethod
    def _expanded_axis_boxes(length: int, count: int, overlap: float) -> list[tuple[int, int]]:
        base = length / count
        expansion = base * overlap
        boxes: list[tuple[int, int]] = []
        for index in range(count):
            left = max(0, math.floor(index * base - expansion))
            right = min(length, math.ceil((index + 1) * base + expansion))
            if not 0 <= left < right <= length:
                raise RuntimeError("Calculated an invalid tile boundary.")
            boxes.append((left, right))
        return boxes

    @staticmethod
    def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
        if image.mode not in ("L", "RGB"):
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()

    @staticmethod
    def _source_identity(filename: str) -> tuple[str, str, int]:
        stem = re.sub(r"\.[^.]+$", "", filename)
        match = re.match(r"^(?P<pdf>.+)_page_(?P<page>\d+)$", stem, flags=re.IGNORECASE)
        if match:
            return stem, f"{match.group('pdf')}.pdf", int(match.group("page"))
        return stem, f"{stem}.pdf", 1

    @staticmethod
    def _document_stem(prefix: str) -> str:
        return re.sub(r"_page_\d+$", "", prefix, flags=re.IGNORECASE)

    @staticmethod
    def _as_int(value: Any, name: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be an integer.")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer.") from exc
        if not number.is_integer():
            raise ValueError(f"{name} must be an integer.")
        return int(number)

    @staticmethod
    def _as_float(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number.") from exc

    @staticmethod
    def _as_bool(value: Any, name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ValueError(f"{name} must be a boolean.")
