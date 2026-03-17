"""
src.processing.coordinates
Conversão de coordenadas e cálculo de bounding boxes.
Extraído e evoluído de utils/wms.py para uso multi-satélite.
"""

from __future__ import annotations

from pyproj import Transformer

_transformer_cache: dict[str, Transformer] = {}


def _get_transformer(srid_from: str, srid_to: str = "EPSG:4326") -> Transformer:
    """Retorna um Transformer com cache por par de CRS."""
    key = f"{srid_from}→{srid_to}"
    if key not in _transformer_cache:
        _transformer_cache[key] = Transformer.from_crs(
            srid_from, srid_to, always_xy=True
        )
    return _transformer_cache[key]


def calcular_bbox_latlon(
    x: float,
    y: float,
    buffer_metros: float,
    srid_entrada: str,
) -> tuple[float, float, float, float]:
    """
    Calcula bounding box em EPSG:4326 a partir de ponto central em UTM.

    Retorna (lon_min, lat_min, lon_max, lat_max).
    """
    xmin = x - buffer_metros
    ymin = y - buffer_metros
    xmax = x + buffer_metros
    ymax = y + buffer_metros

    t = _get_transformer(srid_entrada, "EPSG:4326")
    lon_min, lat_min = t.transform(xmin, ymin)
    lon_max, lat_max = t.transform(xmax, ymax)

    return (lon_min, lat_min, lon_max, lat_max)


def transform_bbox(
    bbox: tuple[float, float, float, float],
    crs_from: str,
    crs_to: str,
) -> tuple[float, float, float, float]:
    """Transforma um bbox entre dois CRS arbitrários."""
    t = _get_transformer(crs_from, crs_to)
    x1, y1 = t.transform(bbox[0], bbox[1])
    x2, y2 = t.transform(bbox[2], bbox[3])
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
