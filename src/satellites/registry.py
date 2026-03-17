"""
src.satellites.registry
Factory e registro de provedores de satélite.
Mapeia nome do satélite → classe do provedor.
"""

from __future__ import annotations

import logging
from typing import Type

from src.core.config import PipelineConfig, SatelliteConfig
from src.satellites.base import BaseSatellite
from src.satellites.cbers import CbersProvider
from src.satellites.kompsat import KompsatProvider
from src.satellites.landsat import LandsatProvider
from src.satellites.sentinel import SentinelProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type[BaseSatellite]] = {
    "kompsat": KompsatProvider,
    "sentinel": SentinelProvider,
    "landsat": LandsatProvider,
    "cbers": CbersProvider,
}


def get_provider(
    satellite_name: str,
    config: PipelineConfig,
) -> BaseSatellite:
    """
    Instancia o provedor correto para o satélite dado.

    Raises:
        ValueError se o satélite não é suportado ou não está configurado.
    """
    name_lower = satellite_name.lower().strip()

    if name_lower not in _REGISTRY:
        supported = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(
            f"Satélite '{satellite_name}' não suportado. "
            f"Opções: {supported}"
        )

    if name_lower not in config.satellites:
        raise ValueError(
            f"Satélite '{satellite_name}' não encontrado na configuração YAML. "
            f"Verifique config.yaml → satellites."
        )

    sat_config = config.satellites[name_lower]
    provider_cls = _REGISTRY[name_lower]
    provider = provider_cls(config, sat_config)

    if not provider.validate():
        raise ValueError(
            f"Validação falhou para o satélite '{satellite_name}'. "
            f"Verifique a configuração."
        )

    logger.info(f"Provedor instanciado: {provider}")
    return provider


def list_satellites() -> list[str]:
    """Retorna nomes dos satélites suportados."""
    return sorted(_REGISTRY.keys())


def register_satellite(name: str, cls: Type[BaseSatellite]) -> None:
    """Registra um novo provedor de satélite (extensibilidade)."""
    _REGISTRY[name.lower()] = cls
    logger.info(f"Satélite registrado: {name} → {cls.__name__}")
