"""
src.satellites.kompsat
Provedor KOMPSAT — adapter WMS sobre o serviço GeoBases ES.
Mantém total compatibilidade com o pipeline legado.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Any

import aiohttp
import numpy as np
from PIL import Image

from src.core.config import PipelineConfig, SatelliteConfig
from src.processing.geotiff import save_png_as_geotiff
from src.satellites.base import BaseSatellite

logger = logging.getLogger(__name__)


def _build_wms_params(
    camada: str,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
    srid: str,
    versao: str,
    formato: str,
    transparente: str,
) -> dict[str, Any]:
    """Monta parâmetros WMS GetMap (1.3.0 com bbox lat/lon invertido)."""
    minx, miny, maxx, maxy = bbox
    bbox_str = f"{miny},{minx},{maxy},{maxx}"

    return {
        "service": "WMS",
        "version": versao,
        "request": "GetMap",
        "layers": camada,
        "bbox": bbox_str,
        "width": width,
        "height": height,
        "crs": srid,
        "format": formato,
        "styles": "",
        "transparent": transparente,
    }


class KompsatProvider(BaseSatellite):
    """
    Provedor KOMPSAT via WMS (GeoBases ES).
    Mantém o fluxo legado: GetMap → PNG → GeoTIFF.
    """

    def search(
        self,
        bbox: tuple[float, float, float, float],
        date_range: str,
        cloud_cover: int,
    ) -> list[dict[str, Any]]:
        """
        WMS não tem busca real. Retorna item dummy indicando que o serviço
        está disponível para o bbox. A validação real acontece no download.
        """
        return [{"type": "wms", "bbox": bbox, "camada": self.sat_config.camada}]

    def select_best_item(self, items: list[Any]) -> dict[str, Any] | None:
        """Para WMS há apenas um 'item' — o serviço em si."""
        return items[0] if items else None

    def get_assets(self, item: Any) -> dict[str, str]:
        """
        Retorna dict com chave 'rgb' e valor da camada WMS.
        Diferente do STAC (onde cada banda é um asset separado).
        """
        return {"rgb": item["camada"]}

    async def download(
        self,
        session: aiohttp.ClientSession,
        assets: dict[str, str],
        output_path: str | Path,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> str:
        """Baixa imagem WMS e converte para GeoTIFF."""
        camada = assets["rgb"]
        params = _build_wms_params(
            camada=camada,
            bbox=bbox,
            width=width,
            height=height,
            srid="EPSG:4326",
            versao=self.config.wms_versao,
            formato=self.config.wms_formato,
            transparente=self.config.wms_transparente,
        )

        timeout = aiohttp.ClientTimeout(total=self.config.timeout_requisicao)

        for attempt in range(1, self.config.tentativas_por_imagem + 1):
            try:
                async with session.get(
                    self.config.wms_url, params=params, timeout=timeout
                ) as resp:
                    resp.raise_for_status()
                    content_type = resp.headers.get("Content-Type", "")
                    if "xml" in content_type or "text" in content_type:
                        body = await resp.text()
                        raise RuntimeError(f"WMS retornou erro: {body[:300]}")

                    content = await resp.read()

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    save_png_as_geotiff,
                    content, output_path, bbox, width, height, self.config.epsg_saida,
                )
                return "ok"

            except Exception as e:
                self.logger.warning(
                    f"Tentativa {attempt}/{self.config.tentativas_por_imagem}: {e}"
                )
                if attempt < self.config.tentativas_por_imagem:
                    await asyncio.sleep(self.config.pausa_entre_tentativas)

        return "erro"

    def get_bands(self) -> list[str]:
        return self.sat_config.default_bands

    def validate(self) -> bool:
        if not self.sat_config.camada:
            self.logger.error("KOMPSAT: camada WMS não configurada.")
            return False
        return super().validate()
