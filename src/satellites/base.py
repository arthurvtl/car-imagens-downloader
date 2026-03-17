"""
src.satellites.base
Contrato abstrato para provedores de satélite.

Todo provedor (KOMPSAT, Sentinel, Landsat, CBERS) DEVE herdar de
BaseSatellite e implementar todos os métodos abstratos.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.core.config import PipelineConfig, SatelliteConfig

logger = logging.getLogger(__name__)


class BaseSatellite(ABC):
    """
    Contrato base para provedores de satélite.

    Fluxo esperado:
        items = provider.search(bbox, date_range, cloud_cover)
        best  = provider.select_best_item(items)
        assets = provider.get_assets(best)
        await provider.download(assets, output_path, bbox, width, height)
    """

    def __init__(self, config: PipelineConfig, sat_config: SatelliteConfig) -> None:
        self.config = config
        self.sat_config = sat_config
        self.logger = logging.getLogger(f"{__name__}.{sat_config.name}")

    @property
    def name(self) -> str:
        return self.sat_config.name

    @property
    def satellite_type(self) -> str:
        return self.sat_config.type

    @abstractmethod
    def search(
        self,
        bbox: tuple[float, float, float, float],
        date_range: str,
        cloud_cover: int,
    ) -> list[Any]:
        """
        Busca imagens/cenas disponíveis para o bbox e período.
        Para WMS, retorna lista com elemento único (dummy).
        Para STAC, retorna lista de pystac.Item.
        """

    @abstractmethod
    def select_best_item(self, items: list[Any]) -> Any | None:
        """
        Seleciona o melhor item da lista retornada por search().
        Critério padrão: menor cobertura de nuvens.
        """

    @abstractmethod
    def get_assets(self, item: Any) -> dict[str, str]:
        """
        Retorna dicionário {band_name: url_or_params} para download.
        """

    @abstractmethod
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
        Baixa os assets e salva como GeoTIFF.
        Retorna "ok" ou "erro".
        """

    @abstractmethod
    def get_bands(self) -> list[str]:
        """Retorna lista de nomes das bandas padrão do satélite."""

    def validate(self) -> bool:
        """
        Valida se o provedor está corretamente configurado.
        Retorna True se OK, False se há problemas.
        """
        if not self.sat_config.bands:
            self.logger.error(f"Satélite {self.name}: nenhuma banda configurada.")
            return False
        if not self.sat_config.default_bands:
            self.logger.error(f"Satélite {self.name}: nenhuma banda padrão definida.")
            return False
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} type={self.satellite_type}>"
