"""
src.core.config
Carrega e valida a configuração YAML do pipeline multi-satélite.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


@dataclass
class SatelliteConfig:
    """Configuração de um provedor de satélite."""
    name: str
    type: str  # "wms" ou "stac"
    bands: dict[str, dict[str, Any]]
    default_bands: list[str]
    description: str = ""
    catalog_url: str = ""
    collection: str = ""
    needs_signing: bool = False
    camada: str = ""  # apenas WMS


@dataclass
class PipelineConfig:
    """Configuração completa do pipeline."""
    # Geral
    buffer_metros: int = 1024
    largura_pixels: int = 1024
    altura_pixels: int = 1024
    workers_paralelos: int = 4
    timeout_requisicao: int = 60
    tentativas_por_imagem: int = 3
    pausa_entre_tentativas: int = 2

    # Coordenadas
    srid_entrada: str = "EPSG:31984"
    epsg_saida: int = 4326

    # CSV
    separador_csv: str = ";"

    # WMS (legado)
    wms_url: str = "https://ide.geobases.es.gov.br/geoserver/ows"
    wms_versao: str = "1.3.0"
    wms_formato: str = "image/png"
    wms_transparente: str = "FALSE"

    # Camada segmentada
    camada_segmentada: str = "geonode:ijsn_map_uso_solo_es_2019_20200"
    segmentada_only_es: bool = True

    # Satélites (carregados dinamicamente)
    satellites: dict[str, SatelliteConfig] = field(default_factory=dict)

    # Datas
    date_start: str = "2023-01-01"
    date_end: str = "2024-12-31"

    # Cloud cover
    cloud_cover_max: int = 20

    # Saída
    prefixo_arquivo: str = "amostra"
    pasta_artifacts: str = "artifacts"
    pasta_logs: str = "logs"
    nome_manifesto: str = "dataset_manifesto.csv"
    nome_log: str = "execucao.log"

    # Parâmetros de execução (definidos em runtime)
    arquivo_csv: str = ""
    pasta_saida: str = "saida"
    satellite_name: str = "kompsat"
    download_segmentada: bool = False
    limite_amostras: int | None = None

    @property
    def active_satellite(self) -> SatelliteConfig:
        """Retorna a configuração do satélite ativo."""
        return self.satellites[self.satellite_name]


def _parse_satellite(name: str, raw: dict[str, Any]) -> SatelliteConfig:
    """Converte dicionário YAML em SatelliteConfig."""
    return SatelliteConfig(
        name=name,
        type=raw.get("type", "stac"),
        bands=raw.get("bands", {}),
        default_bands=raw.get("default_bands", []),
        description=raw.get("description", ""),
        catalog_url=raw.get("catalog_url", ""),
        collection=raw.get("collection", ""),
        needs_signing=raw.get("needs_signing", False),
        camada=raw.get("camada", ""),
    )


def load_config(config_path: str | Path | None = None) -> PipelineConfig:
    """
    Carrega a configuração de um arquivo YAML.
    Se nenhum caminho for dado, usa o config.yaml na raiz do projeto.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.warning(f"Arquivo de configuração não encontrado: {path}. Usando padrões.")
        return PipelineConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    general = raw.get("general", {})
    coords = raw.get("coordinates", {})
    csv_cfg = raw.get("csv", {})
    wms_cfg = raw.get("wms", {})
    seg_cfg = raw.get("segmented_layer", {})
    sat_raw = raw.get("satellites", {})
    date_cfg = raw.get("date_range", {})
    cloud_cfg = raw.get("cloud_cover", {})
    out_cfg = raw.get("output", {})

    satellites = {
        name: _parse_satellite(name, data)
        for name, data in sat_raw.items()
    }

    return PipelineConfig(
        buffer_metros=general.get("buffer_metros", 1024),
        largura_pixels=general.get("largura_pixels", 1024),
        altura_pixels=general.get("altura_pixels", 1024),
        workers_paralelos=general.get("workers_paralelos", 4),
        timeout_requisicao=general.get("timeout_requisicao", 60),
        tentativas_por_imagem=general.get("tentativas_por_imagem", 3),
        pausa_entre_tentativas=general.get("pausa_entre_tentativas", 2),
        srid_entrada=coords.get("srid_entrada", "EPSG:31984"),
        epsg_saida=coords.get("epsg_saida", 4326),
        separador_csv=csv_cfg.get("separador", ";"),
        wms_url=wms_cfg.get("url", "https://ide.geobases.es.gov.br/geoserver/ows"),
        wms_versao=wms_cfg.get("versao", "1.3.0"),
        wms_formato=wms_cfg.get("formato", "image/png"),
        wms_transparente=wms_cfg.get("transparente", "FALSE"),
        camada_segmentada=seg_cfg.get("camada", "geonode:ijsn_map_uso_solo_es_2019_20200"),
        segmentada_only_es=seg_cfg.get("only_es", True),
        satellites=satellites,
        date_start=date_cfg.get("start", "2023-01-01"),
        date_end=date_cfg.get("end", "2024-12-31"),
        cloud_cover_max=cloud_cfg.get("max_percent", 20),
        prefixo_arquivo=out_cfg.get("prefixo_arquivo", "amostra"),
        pasta_artifacts=out_cfg.get("pasta_artifacts", "artifacts"),
        pasta_logs=out_cfg.get("pasta_logs", "logs"),
        nome_manifesto=out_cfg.get("nome_manifesto", "dataset_manifesto.csv"),
        nome_log=out_cfg.get("nome_log", "execucao.log"),
    )
