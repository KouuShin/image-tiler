# Image Tiler

An offline Dify Tool plugin that accepts `images: Array[File]` and emits JPEG overview and overlapping local tiles through Dify's fixed `files: Array[File]` output. The full manifest is returned through fixed `text`; fixed `json` contains one source-image object per element.

Maintainer: KouuShin  
Source: https://github.com/KouuShin/image-tiler

## Contract

- Input order is preserved. Per page, output order is overview (when enabled), then `R1C1 … RnCm` in row-major order.
- Tile windows are proportional to the supplied dimensions. No image layout or crop coordinate is hard-coded.
- `overlap_ratio` expands every base-grid tile on each side by 15% of the base tile width/height, clipped to source bounds.
- Each page has `contentClassification: "unknown"`; no empty-page classification or suppression occurs.
- Any invalid input or one-page processing failure ends the tool invocation. Nothing is silently skipped.

## Installation

1. Download the latest `.difypkg` from this repository.
2. In Dify, open **Plugins → Install Plugin → Local Package** and select the downloaded file.
3. Add **Image Tiler / 图片切片** as a Tool node and connect a JPEG or PNG `Array[File]` to `images`.
4. Adjust rows, columns, overlap, JPEG quality, and overview output as needed.

## Output

With the defaults, each input image produces one overview and nine overlapping tiles. The plugin also returns a manifest that maps every output file to its source image and tile coordinates.
