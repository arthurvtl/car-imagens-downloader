"""
src.stac.client
Wrapper sobre pystac-client + planetary-computer para busca STAC unificada.

Responsabilidades:
  - Conectar a catálogos STAC (Planetary Computer, INPE/BDC)
  - Buscar items por bbox, intervalo de datas e cloud cover
  - Assinar URLs de assets quando necessário (Planetary Computer)
"""

from __future__ import annotations

import logging
from typing import Any

import pystac
from pystac_client import Client

logger = logging.getLogger(__name__)

_catalog_cache: dict[str, Client] = {}


def get_catalog(
    catalog_url: str,
    needs_signing: bool = False,
) -> Client:
    """
    Retorna um cliente STAC com cache por URL.
    Se needs_signing=True, aplica planetary_computer.sign_inplace como modifier.
    """
    key = catalog_url
    if key not in _catalog_cache:
        modifier = None
        if needs_signing:
            try:
                import planetary_computer
                modifier = planetary_computer.sign_inplace
                logger.info("Planetary Computer: assinatura de assets ativada.")
            except ImportError:
                logger.warning(
                    "planetary-computer não instalado. "
                    "Assets do Planetary Computer podem falhar sem assinatura."
                )

        _catalog_cache[key] = Client.open(catalog_url, modifier=modifier)
        logger.info(f"Catálogo STAC conectado: {catalog_url}")

    return _catalog_cache[key]


def search_items(
    catalog_url: str,
    collection: str,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_cloud_cover: int = 20,
    needs_signing: bool = False,
    max_items: int = 50,
) -> list[pystac.Item]:
    """
    Busca items STAC que intersectam o bbox dado.

    Parâmetros:
        catalog_url: URL do catálogo STAC
        collection: nome da coleção (ex: "sentinel-2-l2a")
        bbox: (lon_min, lat_min, lon_max, lat_max) em EPSG:4326
        datetime_range: string "YYYY-MM-DD/YYYY-MM-DD"
        max_cloud_cover: % máximo de nuvens (0-100)
        needs_signing: se True, assina assets via Planetary Computer
        max_items: número máximo de items retornados

    Retorna lista de pystac.Item ordenada por cloud_cover (menor primeiro).
    """
    catalog = get_catalog(catalog_url, needs_signing)

    query_params: dict[str, Any] = {}
    query_params["eo:cloud_cover"] = {"lt": max_cloud_cover}

    try:
        search = catalog.search(
            collections=[collection],
            bbox=list(bbox),
            datetime=datetime_range,
            query=query_params,
            max_items=max_items,
        )
        items = list(search.items())
    except Exception as e:
        logger.error(f"Erro na busca STAC ({collection}): {e}")
        return []

    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    logger.info(
        f"STAC search: {len(items)} items encontrados para {collection} "
        f"(bbox={bbox}, cloud<{max_cloud_cover}%)"
    )

    return items


def get_asset_url(item: pystac.Item, band_key: str) -> str | None:
    """
    Obtém a URL de um asset específico de um Item STAC.
    Tenta o band_key diretamente; se não existir, tenta variações comuns.
    """
    if band_key in item.assets:
        return item.assets[band_key].href

    key_lower = band_key.lower()
    for asset_key, asset in item.assets.items():
        if asset_key.lower() == key_lower:
            return asset.href

    logger.warning(
        f"Asset '{band_key}' não encontrado no item {item.id}. "
        f"Assets disponíveis: {list(item.assets.keys())}"
    )
    return None


def select_best_item(
    items: list[pystac.Item],
    required_bands: list[str] | None = None,
) -> pystac.Item | None:
    """
    Seleciona o melhor item (menor cobertura de nuvens) que contenha
    todas as bandas requeridas.
    """
    if not items:
        return None

    if not required_bands:
        return items[0]

    for item in items:
        asset_keys = set(item.assets.keys())
        asset_keys_lower = {k.lower() for k in asset_keys}
        if all(
            b in asset_keys or b.lower() in asset_keys_lower
            for b in required_bands
        ):
            cloud = item.properties.get("eo:cloud_cover", "?")
            logger.info(
                f"Melhor item selecionado: {item.id} (cloud={cloud}%)"
            )
            return item

    logger.warning(
        f"Nenhum item contém todas as bandas {required_bands}. "
        f"Usando o primeiro item disponível."
    )
    return items[0]
