"""
src.satellites.sentinel
Provedor Sentinel-2 via STAC (Microsoft Planetary Computer).

Bandas principais:
  B04 (Red, 10m), B03 (Green, 10m), B02 (Blue, 10m),
  B08 (NIR, 10m), B11 (SWIR-1, 20m), B12 (SWIR-2, 20m)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pystac

from src.core.config import PipelineConfig, SatelliteConfig
from src.processing.geotiff import save_geotiff
from src.processing.raster import read_cog_window
from src.satellites.base import BaseSatellite
from src.stac.client import get_asset_url, search_items, select_best_item

logger = logging.getLogger(__name__)


class SentinelProvider(BaseSatellite):
    """Provedor Sentinel-2 Level-2A via Planetary Computer STAC."""

    def search(
        self,
        bbox: tuple[float, float, float, float],
        date_range: str,
        cloud_cover: int,
    ) -> list[pystac.Item]:
        return search_items(
            catalog_url=self.sat_config.catalog_url,
            collection=self.sat_config.collection,
            bbox=bbox,
            datetime_range=date_range,
            max_cloud_cover=cloud_cover,
            needs_signing=self.sat_config.needs_signing,
        )

    def select_best_item(self, items: list[pystac.Item]) -> pystac.Item | None:
        return select_best_item(items, self.sat_config.default_bands)

    def get_assets(self, item: pystac.Item) -> dict[str, str]:
        assets: dict[str, str] = {}
        for band in self.sat_config.default_bands:
            url = get_asset_url(item, band)
            if url:
                assets[band] = url
            else:
                self.logger.warning(f"Banda {band} não encontrada no item {item.id}")
        return assets

    async def download(
        self,
        session: Any,
        assets: dict[str, str],
        output_path: str | Path,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> str:
        """
        Para cada banda: lê janela do COG remoto (via rasterio em thread executor).
        Empilha as bandas e salva como GeoTIFF multi-banda.
        """
        loop = asyncio.get_running_loop()
        band_arrays: list[np.ndarray] = []
        band_names: list[str] = []

        for band_key, url in assets.items():
            try:
                data = await loop.run_in_executor(
                    None,
                    read_cog_window,
                    url, bbox, width, height,
                )
                band_arrays.append(data)
                band_names.append(band_key)
                self.logger.debug(f"Banda {band_key}: OK ({data.shape})")
            except Exception as e:
                self.logger.error(f"Erro ao ler banda {band_key}: {e}")
                return "erro"

        if not band_arrays:
            self.logger.error("Nenhuma banda foi lida com sucesso.")
            return "erro"

        try:
            stacked = np.stack(band_arrays, axis=0)

            if stacked.dtype != np.uint8:
                for i in range(stacked.shape[0]):
                    band = stacked[i].astype(np.float64)
                    p2, p98 = np.percentile(band[band > 0], [2, 98]) if np.any(band > 0) else (0, 1)
                    if p98 > p2:
                        band = np.clip((band - p2) / (p98 - p2) * 255, 0, 255)
                    stacked[i] = band.astype(np.uint8)
                stacked = stacked.astype(np.uint8)

            await loop.run_in_executor(
                None,
                save_geotiff,
                stacked,
                output_path,
                bbox,
                self.config.epsg_saida,
                band_names,
            )
            return "ok"
        except Exception as e:
            self.logger.error(f"Erro ao salvar GeoTIFF: {e}")
            return "erro"

    def get_bands(self) -> list[str]:
        return self.sat_config.default_bands

    def validate(self) -> bool:
        if not self.sat_config.catalog_url:
            self.logger.error("Sentinel: catalog_url não configurado.")
            return False
        if not self.sat_config.collection:
            self.logger.error("Sentinel: collection não configurada.")
            return False
        return super().validate()
