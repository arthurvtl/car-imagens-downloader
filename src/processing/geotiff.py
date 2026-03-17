"""
src.processing.geotiff
Escrita de GeoTIFF georreferenciados a partir de arrays numpy.
Evolução de utils/wms.py para suportar múltiplas bandas e fontes.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from PIL import Image

logger = logging.getLogger(__name__)


def png_to_array(content: bytes) -> np.ndarray:
    """Decodifica bytes PNG em array numpy (H, W, C)."""
    img = Image.open(io.BytesIO(content)).convert("RGB")
    return np.array(img)


def save_geotiff(
    data: np.ndarray,
    output_path: str | Path,
    bbox: tuple[float, float, float, float],
    epsg: int = 4326,
    band_names: list[str] | None = None,
    compress: str = "lzw",
) -> Path:
    """
    Salva array numpy como GeoTIFF georreferenciado.

    data: array com shape (bands, height, width) ou (height, width, bands).
          Se 2D, trata como banda única.
    bbox: (xmin, ymin, xmax, ymax)
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if data.ndim == 2:
        data = data[np.newaxis, :, :]
    elif data.ndim == 3 and data.shape[2] in (1, 3, 4):
        # (H, W, C) → (C, H, W)
        data = data.transpose(2, 0, 1)

    count, height, width = data.shape
    transform = from_bounds(*bbox, width, height)

    meta = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": data.dtype,
        "crs": CRS.from_epsg(epsg),
        "transform": transform,
        "compress": compress,
    }
    if count == 3:
        meta["photometric"] = "RGB"

    with rasterio.open(path, "w", **meta) as dst:
        dst.write(data)
        if band_names:
            for i, name in enumerate(band_names[:count], 1):
                dst.set_band_description(i, name)

    return path


def save_png_as_geotiff(
    png_content: bytes,
    output_path: str | Path,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
    epsg: int = 4326,
) -> Path:
    """Converte PNG (bytes do WMS) em GeoTIFF — compatibilidade com legado."""
    arr = png_to_array(png_content)
    return save_geotiff(arr, output_path, bbox, epsg)
