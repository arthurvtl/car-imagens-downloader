"""
src.satellites.cbers
Provedor CBERS-4A via STAC (catálogo brasileiro INPE/BDC).

Bandas principais (WPM):
  BAND1 (Blue, 2m), BAND2 (Green, 2m),
  BAND3 (Red, 2m), BAND4 (NIR, 2m)

Fallback: se o catálogo INPE falhar, tenta BDC alternativo.
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

CBERS_FALLBACK_CATALOGS = [
    "https://data.inpe.br/bdc/stac/v1",
    "https://data.inpe.br/stac/v1",
]


class CbersProvider(BaseSatellite):
    """Provedor CBERS-4A WPM via catálogo STAC brasileiro (INPE/BDC)."""

    def search(
        self,
        bbox: tuple[float, float, float, float],
        date_range: str,
        cloud_cover: int,
    ) -> list[pystac.Item]:
        items = search_items(
            catalog_url=self.sat_config.catalog_url,
            collection=self.sat_config.collection,
            bbox=bbox,
            datetime_range=date_range,
            max_cloud_cover=cloud_cover,
            needs_signing=self.sat_config.needs_signing,
        )

        if not items:
            self.logger.info("Catálogo primário sem resultados; tentando fallbacks...")
            for fallback_url in CBERS_FALLBACK_CATALOGS:
                if fallback_url == self.sat_config.catalog_url:
                    continue
                items = search_items(
                    catalog_url=fallback_url,
                    collection=self.sat_config.collection,
                    bbox=bbox,
                    datetime_range=date_range,
                    max_cloud_cover=cloud_cover,
                    needs_signing=False,
                )
                if items:
                    self.logger.info(f"Fallback bem-sucedido: {fallback_url}")
                    break

        return items

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
        """Lê janela de cada banda COG e salva como GeoTIFF multi-banda."""
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
            except Exception as e:
                self.logger.error(f"Erro ao ler banda {band_key}: {e}")
                return "erro"

        if not band_arrays:
            self.logger.error("Nenhuma banda lida com sucesso.")
            return "erro"

        try:
            stacked = np.stack(band_arrays, axis=0)

            if stacked.dtype != np.uint8:
                for i in range(stacked.shape[0]):
                    band = stacked[i].astype(np.float64)
                    valid = band[band > 0]
                    if valid.size > 0:
                        p2, p98 = np.percentile(valid, [2, 98])
                    else:
                        p2, p98 = 0, 1
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
            self.logger.error("CBERS: catalog_url não configurado.")
            return False
        return super().validate()
