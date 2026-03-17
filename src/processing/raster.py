"""
src.processing.raster
Operações raster: leitura de janelas COG, empilhamento de bandas, reprojeção.
Usado pelos provedores STAC para recortar cenas à bbox desejada.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds as window_from_bounds

logger = logging.getLogger(__name__)

# Pool de threads para leituras COG (rasterio é bloqueante)
_cog_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cog-reader")

# Variáveis de ambiente GDAL otimizadas para acesso remoto a COG
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "5",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "5000000",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.vrt",
}


def read_cog_window(
    url: str,
    bbox_4326: tuple[float, float, float, float],
    out_width: int,
    out_height: int,
    band_index: int = 1,
) -> np.ndarray:
    """
    Lê uma janela de um Cloud Optimized GeoTIFF remoto.

    Transforma o bbox de EPSG:4326 para o CRS nativo da cena,
    calcula a janela e lê com reamostragem para as dimensões desejadas.

    Retorna array 2D (height, width).
    """
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(url) as src:
            scene_crs = src.crs

            if scene_crs != CRS.from_epsg(4326):
                scene_bounds = transform_bounds(
                    "EPSG:4326", scene_crs,
                    bbox_4326[0], bbox_4326[1], bbox_4326[2], bbox_4326[3],
                )
            else:
                scene_bounds = bbox_4326

            window = window_from_bounds(*scene_bounds, src.transform)

            data = src.read(
                band_index,
                window=window,
                out_shape=(out_height, out_width),
                resampling=Resampling.bilinear,
            )

            return data


def read_cog_window_multiband(
    url: str,
    bbox_4326: tuple[float, float, float, float],
    out_width: int,
    out_height: int,
) -> np.ndarray:
    """
    Lê TODAS as bandas de um COG remoto dentro da janela.
    Retorna array 3D (bands, height, width).
    """
    with rasterio.Env(**GDAL_ENV):
        with rasterio.open(url) as src:
            scene_crs = src.crs

            if scene_crs != CRS.from_epsg(4326):
                scene_bounds = transform_bounds(
                    "EPSG:4326", scene_crs,
                    bbox_4326[0], bbox_4326[1], bbox_4326[2], bbox_4326[3],
                )
            else:
                scene_bounds = bbox_4326

            window = window_from_bounds(*scene_bounds, src.transform)

            data = src.read(
                window=window,
                out_shape=(src.count, out_height, out_width),
                resampling=Resampling.bilinear,
            )

            return data


def stack_bands(band_arrays: list[np.ndarray]) -> np.ndarray:
    """Empilha lista de arrays 2D em array 3D (bands, H, W)."""
    return np.stack(band_arrays, axis=0)
