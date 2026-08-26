"""Busca STAC e recorte remoto de imagens CBERS.

O modulo atende CLI e Tkinter. A leitura usa GeoTIFF/COG via HTTP Range e
preserva valores radiometricos, georreferenciamento, tipo e nodata.
"""

from __future__ import annotations

import csv
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from requests.adapters import HTTPAdapter
from shapely.geometry import box, shape
from urllib3.util.retry import Retry


class ErroCBERS(RuntimeError):
    """Erro esperado e apresentavel ao usuario."""


@dataclass(frozen=True)
class FonteSTAC:
    codigo: str
    nome: str
    endpoint: str


@dataclass(frozen=True)
class ConfiguracaoColecao:
    colecao: str
    banda_nir: str
    bandas_rgb: tuple[str, str, str]
    escala: float
    nivel: str
    cog: bool


@dataclass(frozen=True)
class SensorCBERS:
    codigo: str
    nome: str
    resolucao_m: float
    fontes: dict[str, ConfiguracaoColecao]


FONTES: dict[str, FonteSTAC] = {
    "inpe": FonteSTAC(
        codigo="inpe",
        nome="INPE (oficial)",
        endpoint="https://data.inpe.br/bdc/stac/v1/",
    ),
    "aws": FonteSTAC(
        codigo="aws",
        nome="AWS (CBERS on AWS)",
        endpoint="https://stac.scitekno.com.br/v100",
    ),
}


SENSORES: dict[str, SensorCBERS] = {
    "wpm": SensorCBERS(
        codigo="wpm",
        nome="CBERS-4A WPM - 8 m",
        resolucao_m=8.0,
        fontes={
            "inpe": ConfiguracaoColecao(
                colecao="CB4A-WPM-L4-DN-1",
                banda_nir="BAND4",
                bandas_rgb=("BAND3", "BAND2", "BAND1"),
                escala=1.0,
                nivel="L4 DN",
                cog=False,
            ),
            "aws": ConfiguracaoColecao(
                colecao="CBERS4A-WPM",
                banda_nir="B4",
                bandas_rgb=("B3", "B2", "B1"),
                escala=1.0,
                nivel="L4 DN",
                cog=True,
            ),
        },
    ),
    "mux4a": SensorCBERS(
        codigo="mux4a",
        nome="CBERS-4A MUX - 16 m",
        resolucao_m=16.0,
        fontes={
            "inpe": ConfiguracaoColecao(
                colecao="CB4A-MUX-L4-SR-1",
                banda_nir="BAND8",
                bandas_rgb=("BAND7", "BAND6", "BAND5"),
                escala=0.0001,
                nivel="L4 SR",
                cog=True,
            ),
        },
    ),
    "mux4": SensorCBERS(
        codigo="mux4",
        nome="CBERS-4 MUX - 20 m",
        resolucao_m=20.0,
        fontes={
            "inpe": ConfiguracaoColecao(
                colecao="CB4-MUX-L4-SR-1",
                banda_nir="BAND8",
                bandas_rgb=("BAND7", "BAND6", "BAND5"),
                escala=0.0001,
                nivel="L4 SR",
                cog=True,
            ),
            "aws": ConfiguracaoColecao(
                colecao="CBERS4-MUX",
                banda_nir="B8",
                bandas_rgb=("B7", "B6", "B5"),
                escala=1.0,
                nivel="L4 DN",
                cog=True,
            ),
        },
    ),
    "wfi4a": SensorCBERS(
        codigo="wfi4a",
        nome="CBERS-4A WFI - 55 m",
        resolucao_m=55.0,
        fontes={
            "inpe": ConfiguracaoColecao(
                colecao="CB4A-WFI-L4-SR-1",
                banda_nir="BAND16",
                bandas_rgb=("BAND15", "BAND14", "BAND13"),
                escala=0.0001,
                nivel="L4 SR",
                cog=True,
            ),
            "aws": ConfiguracaoColecao(
                colecao="CBERS4A-WFI",
                banda_nir="B16",
                bandas_rgb=("B15", "B14", "B13"),
                escala=1.0,
                nivel="L4 DN",
                cog=True,
            ),
        },
    ),
}


@dataclass(frozen=True)
class ConfiguracaoIndice:
    codigo: str
    nome: str
    # banda usada junto do NIR na formula: "vermelho" (bandas_rgb[0]) ou "verde" (bandas_rgb[1])
    papel_banda_extra: str


INDICES: dict[str, ConfiguracaoIndice] = {
    "ndvi": ConfiguracaoIndice("ndvi", "NDVI", "vermelho"),
    "gndvi": ConfiguracaoIndice("gndvi", "GNDVI", "verde"),
    "ndwi": ConfiguracaoIndice("ndwi", "NDWI", "verde"),
}


def calcular_indice(nir: np.ndarray, banda_extra: np.ndarray, codigo: str) -> np.ndarray:
    """(NIR-extra)/(NIR+extra); invertido para ndwi. Fator de escala do sensor
    cancela na razao, entao a conta pode usar os valores brutos das bandas."""
    nir = nir.astype(np.float32)
    extra = banda_extra.astype(np.float32)
    numerador = extra - nir if codigo == "ndwi" else nir - extra
    denominador = nir + extra
    with np.errstate(divide="ignore", invalid="ignore"):
        indice = np.where(denominador != 0, numerador / denominador, np.nan)
    return indice.astype(np.float32)


@dataclass(frozen=True)
class ConfiguracaoExtracao:
    arquivo_csv: Path
    pasta_saida: Path
    produto: str
    fonte: str
    sensor: str
    data_inicial: str
    data_final: str
    buffer_metros: float = 1024.0
    epsg_entrada: str = "EPSG:31984"
    separador_csv: str = ";"
    criterio: str = "menor-nuvem"
    max_nuvens: float | None = None
    largura_pixels: int | None = None
    altura_pixels: int | None = None
    quantidade: int | None = None
    workers: int = 4
    timeout: int = 90
    tentativas: int = 3
    sobrescrever: bool = False
    # Nome da pasta de saida dentro de pasta_saida. "completo" versiona
    # sozinho (IMAGENS, IMAGENS 2, ...) via proxima_pasta_imagens().
    pasta_imagens: str = "IMAGENS"


@dataclass(frozen=True)
class PontoEntrada:
    numero: int
    cod_imovel: str
    x: float
    y: float


@dataclass
class ResultadoExtracao:
    numero: int
    cod_imovel: str
    x: float
    y: float
    produto: str
    fonte: str
    colecao: str
    item_id: str = ""
    data_aquisicao: str = ""
    nuvens_percentual: float | None = None
    bandas: str = ""
    crs_saida: str = ""
    resolucao_x: float | None = None
    resolucao_y: float | None = None
    largura_pixels: int | None = None
    altura_pixels: int | None = None
    bbox_wgs84: tuple[float, float, float, float] | None = None
    caminho_saida: str = ""
    status: str = "erro"
    erro: str = ""

    def como_linha_manifesto(self) -> dict[str, object]:
        bbox = self.bbox_wgs84 or ("", "", "", "")
        return {
            "numero_amostra": self.numero,
            "cod_imovel": self.cod_imovel,
            "x": self.x,
            "y": self.y,
            "produto": self.produto,
            "fonte": self.fonte,
            "colecao": self.colecao,
            "item_id": self.item_id,
            "data_aquisicao": self.data_aquisicao,
            "nuvens_percentual": (
                "" if self.nuvens_percentual is None else self.nuvens_percentual
            ),
            "bandas": self.bandas,
            "crs_saida": self.crs_saida,
            "resolucao_x": (
                "" if self.resolucao_x is None else self.resolucao_x
            ),
            "resolucao_y": (
                "" if self.resolucao_y is None else self.resolucao_y
            ),
            "largura_pixels": (
                "" if self.largura_pixels is None else self.largura_pixels
            ),
            "altura_pixels": (
                "" if self.altura_pixels is None else self.altura_pixels
            ),
            "bbox_lon_min": bbox[0],
            "bbox_lat_min": bbox[1],
            "bbox_lon_max": bbox[2],
            "bbox_lat_max": bbox[3],
            "caminho_saida": self.caminho_saida,
            "status": self.status,
            "erro": self.erro,
            "data_processamento": datetime.now(timezone.utc).isoformat(),
        }


StatusCallback = Callable[[str], None]
ProgressoCallback = Callable[[int, int, ResultadoExtracao], None]


def pixels_para_resolucao(buffer_metros: float, resolucao_m: float) -> tuple[int, int]:
    """Calcula largura/altura em pixels para atingir uma resolucao (m/pixel) dada."""
    if resolucao_m <= 0:
        raise ErroCBERS("resolucao_m deve ser maior que zero.")
    lado_metros = 2 * buffer_metros
    pixels = round(lado_metros / resolucao_m)
    if pixels < 1:
        raise ErroCBERS("resolucao_m muito grande para o buffer informado.")
    return pixels, pixels


def sensores_disponiveis(fonte: str) -> list[SensorCBERS]:
    """Lista sensores suportados por uma fonte."""
    return [sensor for sensor in SENSORES.values() if fonte in sensor.fontes]


def obter_colecao(fonte: str, sensor: str) -> ConfiguracaoColecao:
    if fonte not in FONTES:
        raise ErroCBERS(f"Fonte desconhecida: {fonte}")
    if sensor not in SENSORES or fonte not in SENSORES[sensor].fontes:
        raise ErroCBERS(f"Sensor '{sensor}' indisponivel na fonte '{fonte}'.")
    return SENSORES[sensor].fontes[fonte]


def validar_configuracao(cfg: ConfiguracaoExtracao) -> None:
    if cfg.produto not in {"nir", "rgb", "completo", *INDICES}:
        raise ErroCBERS(
            "Produto deve ser 'nir', 'rgb', 'completo' ou um indice "
            f"({', '.join(INDICES)})."
        )
    obter_colecao(cfg.fonte, cfg.sensor)
    if not cfg.arquivo_csv.is_file():
        raise ErroCBERS(f"CSV nao encontrado: {cfg.arquivo_csv}")
    if cfg.buffer_metros <= 0:
        raise ErroCBERS("Buffer deve ser maior que zero.")
    if cfg.workers < 1:
        raise ErroCBERS("Workers deve ser maior que zero.")
    if cfg.tentativas < 1:
        raise ErroCBERS("Tentativas deve ser maior que zero.")
    if cfg.quantidade is not None and cfg.quantidade < 1:
        raise ErroCBERS("Quantidade deve ser maior que zero.")
    if (cfg.largura_pixels is None) != (cfg.altura_pixels is None):
        raise ErroCBERS("Informe largura e altura juntas, ou deixe ambas vazias.")
    if cfg.largura_pixels is not None and (
        cfg.largura_pixels < 1 or cfg.altura_pixels is None or cfg.altura_pixels < 1
    ):
        raise ErroCBERS("Largura e altura devem ser maiores que zero.")
    if cfg.criterio not in {"menor-nuvem", "mais-recente"}:
        raise ErroCBERS("Criterio deve ser 'menor-nuvem' ou 'mais-recente'.")
    if cfg.max_nuvens is not None and not 0 <= cfg.max_nuvens <= 100:
        raise ErroCBERS("Maximo de nuvens deve ficar entre 0 e 100.")
    try:
        inicio = date.fromisoformat(cfg.data_inicial)
        fim = date.fromisoformat(cfg.data_final)
    except ValueError as exc:
        raise ErroCBERS("Datas devem usar o formato AAAA-MM-DD.") from exc
    if inicio > fim:
        raise ErroCBERS("Data inicial deve ser anterior a data final.")
    try:
        Transformer.from_crs(cfg.epsg_entrada, "EPSG:4326", always_xy=True)
    except Exception as exc:
        raise ErroCBERS(f"CRS de entrada invalido: {cfg.epsg_entrada}") from exc


def carregar_pontos(
    arquivo_csv: Path, separador: str = ";", quantidade: int | None = None
) -> list[PontoEntrada]:
    """Le CSV no formato cod_imovel;x;y."""
    pontos: list[PontoEntrada] = []
    with arquivo_csv.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo, delimiter=separador)
        if not leitor.fieldnames:
            raise ErroCBERS("CSV vazio ou sem cabecalho.")
        nomes = {nome.strip().lower(): nome for nome in leitor.fieldnames}
        faltantes = {"cod_imovel", "x", "y"} - set(nomes)
        if faltantes:
            raise ErroCBERS(
                "CSV deve conter colunas cod_imovel, x e y. "
                f"Faltando: {', '.join(sorted(faltantes))}."
            )
        for numero, linha in enumerate(leitor, start=1):
            if quantidade is not None and len(pontos) >= quantidade:
                break
            try:
                x = float(str(linha[nomes["x"]]).strip().replace(",", "."))
                y = float(str(linha[nomes["y"]]).strip().replace(",", "."))
            except (TypeError, ValueError) as exc:
                raise ErroCBERS(f"Coordenada invalida na linha {numero + 1}.") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ErroCBERS(f"Coordenada invalida na linha {numero + 1}.")
            codigo = str(linha[nomes["cod_imovel"]] or "").strip()
            pontos.append(
                PontoEntrada(
                    numero=numero,
                    cod_imovel=codigo or f"amostra_{numero}",
                    x=x,
                    y=y,
                )
            )
    if not pontos:
        raise ErroCBERS("CSV nao possui linhas de dados.")
    return pontos


def calcular_bbox_wgs84(
    ponto: PontoEntrada, buffer_metros: float, epsg_entrada: str
) -> tuple[float, float, float, float]:
    transformador = Transformer.from_crs(epsg_entrada, "EPSG:4326", always_xy=True)
    return transformador.transform_bounds(
        ponto.x - buffer_metros,
        ponto.y - buffer_metros,
        ponto.x + buffer_metros,
        ponto.y + buffer_metros,
        densify_pts=21,
    )


def _sessao_http(tentativas: int) -> requests.Session:
    retry = Retry(
        total=tentativas,
        connect=tentativas,
        read=tentativas,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    sessao = requests.Session()
    sessao.mount("https://", HTTPAdapter(max_retries=retry))
    sessao.headers["User-Agent"] = "IntegraCAR-CBERS/1.0"
    return sessao


def consultar_itens_stac(
    fonte: str,
    colecao: str,
    bbox_wgs84: tuple[float, float, float, float],
    data_inicial: str,
    data_final: str,
    timeout: int,
    tentativas: int,
    max_itens: int = 200,
) -> list[dict]:
    """Consulta STAC, seguindo paginacao GET/POST."""
    endpoint = FONTES[fonte].endpoint.rstrip("/") + "/search"
    params = {
        "collections": colecao,
        "bbox": ",".join(f"{valor:.10f}" for valor in bbox_wgs84),
        "datetime": (
            f"{data_inicial}T00:00:00Z/{data_final}T23:59:59Z"
        ),
        "limit": min(max_itens, 100),
    }
    itens: list[dict] = []
    ids: set[str] = set()
    proxima_url: str | None = endpoint
    metodo = "GET"
    corpo: dict | None = None
    primeira = True

    with _sessao_http(tentativas) as sessao:
        for _ in range(30):
            if not proxima_url or len(itens) >= max_itens:
                break
            if metodo == "POST":
                resposta = sessao.post(
                    proxima_url,
                    json=corpo or {},
                    timeout=(15, timeout),
                )
            else:
                resposta = sessao.get(
                    proxima_url,
                    params=params if primeira else None,
                    timeout=(15, timeout),
                )
            primeira = False
            if resposta.status_code >= 400:
                detalhe = resposta.text[:300].replace("\n", " ")
                raise ErroCBERS(
                    f"STAC respondeu HTTP {resposta.status_code}: {detalhe}"
                )
            try:
                pagina = resposta.json()
            except requests.JSONDecodeError as exc:
                raise ErroCBERS("STAC retornou resposta que nao e JSON.") from exc
            if pagina.get("type") != "FeatureCollection":
                raise ErroCBERS("Resposta STAC invalida: FeatureCollection ausente.")
            for item in pagina.get("features", []):
                item_id = str(item.get("id", ""))
                if item_id and item_id not in ids:
                    ids.add(item_id)
                    itens.append(item)
                    if len(itens) >= max_itens:
                        break
            link_proximo = next(
                (
                    link
                    for link in pagina.get("links", [])
                    if link.get("rel") == "next" and link.get("href")
                ),
                None,
            )
            if not link_proximo:
                break
            proxima_url = urljoin(resposta.url, link_proximo["href"])
            metodo = str(link_proximo.get("method", "GET")).upper()
            corpo = link_proximo.get("body")
    return itens


def _percentual_nuvens(item: dict) -> float | None:
    valor = item.get("properties", {}).get("eo:cloud_cover")
    try:
        return None if valor is None else float(valor)
    except (TypeError, ValueError):
        return None


def _timestamp_item(item: dict) -> float:
    valor = (
        item.get("properties", {}).get("datetime")
        or item.get("properties", {}).get("start_datetime")
        or ""
    )
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _cobertura_item(
    item: dict, bbox_wgs84: tuple[float, float, float, float]
) -> float:
    area = box(*bbox_wgs84)
    if area.area == 0:
        return 0.0
    try:
        geometria = shape(item["geometry"])
        return max(0.0, min(1.0, geometria.intersection(area).area / area.area))
    except Exception:  # noqa: BLE001 - geometria STAC de terceiros pode ser invalida
        try:
            geometria = box(*item["bbox"])
            return max(0.0, min(1.0, geometria.intersection(area).area / area.area))
        except Exception:  # noqa: BLE001 - item sem geometria/bbox utilizavel
            return 0.0


def selecionar_item(
    itens: Iterable[dict],
    bbox_wgs84: tuple[float, float, float, float],
    assets_necessarios: tuple[str, ...],
    criterio: str,
    max_nuvens: float | None,
) -> dict:
    candidatos: list[tuple[dict, float, float | None, float]] = []
    for item in itens:
        assets = item.get("assets", {})
        if any(nome not in assets or not assets[nome].get("href") for nome in assets_necessarios):
            continue
        nuvens = _percentual_nuvens(item)
        if max_nuvens is not None and nuvens is not None and nuvens > max_nuvens:
            continue
        cobertura = _cobertura_item(item, bbox_wgs84)
        if cobertura <= 0:
            continue
        candidatos.append((item, cobertura, nuvens, _timestamp_item(item)))

    if not candidatos:
        raise ErroCBERS(
            "Nenhuma cena com as bandas pedidas cobre o recorte e passa nos filtros."
        )

    def chave_menor_nuvem(
        candidato: tuple[dict, float, float | None, float]
    ) -> tuple[float, ...]:
        _, cobertura, nuvens, timestamp = candidato
        return (
            0 if cobertura >= 0.999 else 1,
            1 if nuvens is None else 0,
            101.0 if nuvens is None else nuvens,
            -cobertura,
            -timestamp,
        )

    def chave_mais_recente(
        candidato: tuple[dict, float, float | None, float]
    ) -> tuple[float, ...]:
        _, cobertura, nuvens, timestamp = candidato
        return (
            0 if cobertura >= 0.999 else 1,
            -timestamp,
            1 if nuvens is None else 0,
            101.0 if nuvens is None else nuvens,
            -cobertura,
        )

    chave = chave_menor_nuvem if criterio == "menor-nuvem" else chave_mais_recente
    return min(candidatos, key=chave)[0]


def href_para_https(href: str) -> str:
    """Converte s3:// publico do CBERS on AWS para HTTPS."""
    if not href.startswith("s3://"):
        return href
    partes = urlparse(href)
    bucket = partes.netloc
    chave = quote(partes.path.lstrip("/"), safe="/%")
    regiao = "us-west-2" if bucket == "brazil-eosats" else "us-east-1"
    return f"https://{bucket}.s3.{regiao}.amazonaws.com/{chave}"


def _mesma_grade(src, referencia) -> bool:
    return (
        src.crs == referencia.crs
        and src.width == referencia.width
        and src.height == referencia.height
        and src.transform.almost_equals(referencia.transform)
    )


def _janela_dentro_raster(janela: Window, largura: int, altura: int) -> bool:
    return (
        janela.col_off >= 0
        and janela.row_off >= 0
        and janela.col_off + janela.width <= largura
        and janela.row_off + janela.height <= altura
    )


def _ler_bandas(
    assets: list[tuple[str, str]],
    ponto: PontoEntrada,
    cfg: ConfiguracaoExtracao,
) -> tuple[np.ndarray, dict[str, object]]:
    """Le bandas remotas ja alinhadas na mesma grade (recorte + resample).

    Devolve o array empilhado (n_bandas, altura, largura) e os metadados de
    grade (crs, transform, nodata, largura, altura) do recorte.
    """
    ambiente_gdal = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
        "GDAL_HTTP_MULTIRANGE": "YES",
        "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": 20_000_000,
    }
    with rasterio.Env(**ambiente_gdal), ExitStack() as pilha:
        datasets = [
            pilha.enter_context(rasterio.open(href_para_https(href)))
            for _, href in assets
        ]
        referencia = datasets[0]
        if referencia.crs is None:
            raise ErroCBERS("Asset nao possui CRS.")

        transformador = Transformer.from_crs(
            cfg.epsg_entrada, referencia.crs, always_xy=True
        )
        limites = transformador.transform_bounds(
            ponto.x - cfg.buffer_metros,
            ponto.y - cfg.buffer_metros,
            ponto.x + cfg.buffer_metros,
            ponto.y + cfg.buffer_metros,
            densify_pts=21,
        )
        janela_float = rasterio.windows.from_bounds(
            *limites, transform=referencia.transform
        )

        redimensionar = cfg.largura_pixels is not None
        if redimensionar:
            largura_saida = int(cfg.largura_pixels or 0)
            altura_saida = int(cfg.altura_pixels or 0)
            janela = janela_float
            transformacao_saida = from_bounds(
                *limites, largura_saida, altura_saida
            )
        else:
            janela = janela_float.round_offsets().round_lengths()
            largura_saida = max(1, int(janela.width))
            altura_saida = max(1, int(janela.height))
            transformacao_saida = referencia.window_transform(janela)

        matrizes: list[np.ndarray] = []
        nodata = referencia.nodata
        for src in datasets:
            leitor = src
            if not _mesma_grade(src, referencia):
                leitor = pilha.enter_context(
                    WarpedVRT(
                        src,
                        crs=referencia.crs,
                        transform=referencia.transform,
                        width=referencia.width,
                        height=referencia.height,
                        resampling=Resampling.bilinear,
                    )
                )
            parametros: dict[str, object] = {"window": janela}
            if redimensionar:
                parametros["out_shape"] = (altura_saida, largura_saida)
                parametros["resampling"] = Resampling.bilinear
            if not _janela_dentro_raster(
                janela, leitor.width, leitor.height
            ):
                parametros["boundless"] = True
                parametros["fill_value"] = nodata if nodata is not None else 0
            matriz = leitor.read(1, **parametros)
            if matriz.shape != (altura_saida, largura_saida):
                raise ErroCBERS(
                    "Bandas produziram dimensoes diferentes no recorte."
                )
            matrizes.append(matriz)

        dados = np.stack(matrizes)
        return dados, {
            "crs": referencia.crs,
            "transform": transformacao_saida,
            "nodata": nodata,
            "largura": largura_saida,
            "altura": altura_saida,
        }


def _gravar_geotiff(
    dados: np.ndarray,
    grade: dict[str, object],
    caminho_saida: Path,
    nomes_bandas: list[str],
    escalas: tuple[float, ...],
    tags: dict[str, object],
    colorinterp: tuple[ColorInterp, ...] | None = None,
) -> None:
    """Grava um array (n_bandas, altura, largura) ja recortado como GeoTIFF."""
    temporario = caminho_saida.with_name(caminho_saida.stem + ".part.tif")
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    temporario.unlink(missing_ok=True)

    perfil = {
        "driver": "GTiff",
        "width": grade["largura"],
        "height": grade["altura"],
        "count": dados.shape[0],
        "dtype": dados.dtype,
        "crs": grade["crs"],
        "transform": grade["transform"],
        "nodata": grade["nodata"],
        "compress": "deflate",
        "predictor": 2 if np.issubdtype(dados.dtype, np.integer) else 3,
        "BIGTIFF": "IF_SAFER",
    }
    try:
        with rasterio.open(temporario, "w", **perfil) as destino:
            destino.write(dados)
            destino.scales = escalas
            for indice, nome_banda in enumerate(nomes_bandas, start=1):
                destino.set_band_description(indice, nome_banda)
            if colorinterp is not None:
                destino.colorinterp = colorinterp
            destino.update_tags(
                **{
                    chave: "" if valor is None else str(valor)
                    for chave, valor in tags.items()
                }
            )
        os.replace(temporario, caminho_saida)
    except Exception:
        temporario.unlink(missing_ok=True)
        raise


def recortar_assets(
    assets: list[tuple[str, str]],
    caminho_saida: Path,
    ponto: PontoEntrada,
    cfg: ConfiguracaoExtracao,
    escala: float,
    tags: dict[str, object],
) -> dict[str, object]:
    """Le bandas remotas e grava um GeoTIFF local."""
    dados, grade = _ler_bandas(assets, ponto, cfg)
    colorinterp = (
        (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
        if len(assets) == 3
        else None
    )
    _gravar_geotiff(
        dados,
        grade,
        caminho_saida,
        nomes_bandas=[nome for nome, _ in assets],
        escalas=tuple(escala for _ in assets),
        tags=tags,
        colorinterp=colorinterp,
    )
    return {
        "crs": str(grade["crs"]),
        "resolucao": (
            abs(float(grade["transform"].a)),
            abs(float(grade["transform"].e)),
        ),
        "largura": grade["largura"],
        "altura": grade["altura"],
    }


def _subpasta_saida(produto: str) -> str:
    if produto in INDICES:
        return INDICES[produto].nome
    if produto == "completo":
        return "NIR"
    return "NIR" if produto == "nir" else "RGB"


def _nome_saida(ponto: PontoEntrada, produto: str) -> str:
    if produto in INDICES or produto == "completo":
        sufixo = "nir" if produto == "completo" else produto
    else:
        sufixo = "nir" if produto == "nir" else "rgb"
    return f"amostra_{ponto.numero}_cbers_{sufixo}.tif"


def _caminho_saida(cfg: ConfiguracaoExtracao, ponto: PontoEntrada, produto: str) -> Path:
    return (
        cfg.pasta_saida / cfg.pasta_imagens / _subpasta_saida(produto)
        / _nome_saida(ponto, produto)
    )


def proxima_pasta_imagens(pasta_saida: Path) -> str:
    """Devolve 'IMAGENS', ou 'IMAGENS 2', 'IMAGENS 3'... se ja existir."""
    if not (pasta_saida / "IMAGENS").exists():
        return "IMAGENS"
    numero = 2
    while (pasta_saida / f"IMAGENS {numero}").exists():
        numero += 1
    return f"IMAGENS {numero}"


def _extrair_indice_ponto_sem_retry(
    ponto: PontoEntrada,
    cfg: ConfiguracaoExtracao,
    cancelamento: threading.Event | None,
) -> ResultadoExtracao:
    colecao = obter_colecao(cfg.fonte, cfg.sensor)
    indice_cfg = INDICES[cfg.produto]
    banda_extra_nome = (
        colecao.bandas_rgb[0]
        if indice_cfg.papel_banda_extra == "vermelho"
        else colecao.bandas_rgb[1]
    )
    bandas = (colecao.banda_nir, banda_extra_nome)

    resultado = ResultadoExtracao(
        numero=ponto.numero,
        cod_imovel=ponto.cod_imovel,
        x=ponto.x,
        y=ponto.y,
        produto=cfg.produto,
        fonte=cfg.fonte,
        colecao=colecao.colecao,
    )
    caminho_nir = _caminho_saida(cfg, ponto, "nir")
    caminho_indice = _caminho_saida(cfg, ponto, cfg.produto)
    resultado.caminho_saida = str(caminho_indice)

    if cancelamento and cancelamento.is_set():
        resultado.status = "cancelado"
        return resultado
    if caminho_nir.exists() and caminho_indice.exists() and not cfg.sobrescrever:
        resultado.status = "ignorado"
        return resultado

    bbox = calcular_bbox_wgs84(ponto, cfg.buffer_metros, cfg.epsg_entrada)
    resultado.bbox_wgs84 = bbox
    itens = consultar_itens_stac(
        fonte=cfg.fonte,
        colecao=colecao.colecao,
        bbox_wgs84=bbox,
        data_inicial=cfg.data_inicial,
        data_final=cfg.data_final,
        timeout=cfg.timeout,
        tentativas=cfg.tentativas,
    )
    item = selecionar_item(
        itens=itens,
        bbox_wgs84=bbox,
        assets_necessarios=bandas,
        criterio=cfg.criterio,
        max_nuvens=cfg.max_nuvens,
    )
    propriedades = item.get("properties", {})
    resultado.item_id = str(item.get("id", ""))
    resultado.data_aquisicao = str(
        propriedades.get("datetime") or propriedades.get("start_datetime") or ""
    )
    resultado.nuvens_percentual = _percentual_nuvens(item)
    resultado.bandas = ",".join(bandas)

    assets = [(nome, item["assets"][nome]["href"]) for nome in bandas]
    # As 2 bandas vem do MESMO item STAC (mesma cena, mesma data) para
    # garantir que os pixels de NIR e da banda extra estejam alinhados -
    # senao o indice mistura datas/condicoes diferentes por pixel.
    dados, grade = _ler_bandas(assets, ponto, cfg)
    nir_bruto, extra_bruto = dados[0], dados[1]

    tags_base = {
        "fonte_stac": FONTES[cfg.fonte].endpoint,
        "colecao": colecao.colecao,
        "item_id": resultado.item_id,
        "data_aquisicao": resultado.data_aquisicao,
        "nuvens_percentual": resultado.nuvens_percentual,
        "bandas": resultado.bandas,
        "nivel_processamento": colecao.nivel,
        "fator_escala": colecao.escala,
        "cod_imovel": ponto.cod_imovel,
    }

    _gravar_geotiff(
        nir_bruto[np.newaxis, ...],
        grade,
        caminho_nir,
        nomes_bandas=[colecao.banda_nir],
        escalas=(colecao.escala,),
        tags={**tags_base, "produto": "NIR"},
    )

    indice_array = calcular_indice(nir_bruto, extra_bruto, cfg.produto)
    grade_indice = {**grade, "nodata": float("nan")}
    _gravar_geotiff(
        indice_array[np.newaxis, ...],
        grade_indice,
        caminho_indice,
        nomes_bandas=[indice_cfg.nome],
        escalas=(1.0,),
        tags={**tags_base, "produto": indice_cfg.nome},
    )

    resultado.crs_saida = str(grade["crs"])
    resultado.resolucao_x = abs(float(grade["transform"].a))
    resultado.resolucao_y = abs(float(grade["transform"].e))
    resultado.largura_pixels = int(grade["largura"])
    resultado.altura_pixels = int(grade["altura"])
    resultado.status = "ok"
    return resultado


def _extrair_completo_ponto_sem_retry(
    ponto: PontoEntrada,
    cfg: ConfiguracaoExtracao,
    cancelamento: threading.Event | None,
) -> ResultadoExtracao:
    """Baixa NIR+Vermelho+Verde (3 bandas, 1 cena so) e grava NIR + os 3 indices."""
    colecao = obter_colecao(cfg.fonte, cfg.sensor)
    banda_vermelho, banda_verde = colecao.bandas_rgb[0], colecao.bandas_rgb[1]
    bandas = (colecao.banda_nir, banda_vermelho, banda_verde)

    resultado = ResultadoExtracao(
        numero=ponto.numero,
        cod_imovel=ponto.cod_imovel,
        x=ponto.x,
        y=ponto.y,
        produto=cfg.produto,
        fonte=cfg.fonte,
        colecao=colecao.colecao,
    )
    caminhos = {
        "nir": _caminho_saida(cfg, ponto, "nir"),
        "ndvi": _caminho_saida(cfg, ponto, "ndvi"),
        "gndvi": _caminho_saida(cfg, ponto, "gndvi"),
        "ndwi": _caminho_saida(cfg, ponto, "ndwi"),
    }
    resultado.caminho_saida = str(cfg.pasta_saida / cfg.pasta_imagens)

    if cancelamento and cancelamento.is_set():
        resultado.status = "cancelado"
        return resultado
    if all(caminho.exists() for caminho in caminhos.values()) and not cfg.sobrescrever:
        resultado.status = "ignorado"
        return resultado

    bbox = calcular_bbox_wgs84(ponto, cfg.buffer_metros, cfg.epsg_entrada)
    resultado.bbox_wgs84 = bbox
    itens = consultar_itens_stac(
        fonte=cfg.fonte,
        colecao=colecao.colecao,
        bbox_wgs84=bbox,
        data_inicial=cfg.data_inicial,
        data_final=cfg.data_final,
        timeout=cfg.timeout,
        tentativas=cfg.tentativas,
    )
    item = selecionar_item(
        itens=itens,
        bbox_wgs84=bbox,
        assets_necessarios=bandas,
        criterio=cfg.criterio,
        max_nuvens=cfg.max_nuvens,
    )
    propriedades = item.get("properties", {})
    resultado.item_id = str(item.get("id", ""))
    resultado.data_aquisicao = str(
        propriedades.get("datetime") or propriedades.get("start_datetime") or ""
    )
    resultado.nuvens_percentual = _percentual_nuvens(item)
    resultado.bandas = ",".join(bandas)

    assets = [(nome, item["assets"][nome]["href"]) for nome in bandas]
    # As 3 bandas vem do MESMO item STAC (mesma cena) para os 3 indices
    # ficarem pixel a pixel alinhados entre si.
    dados, grade = _ler_bandas(assets, ponto, cfg)
    nir_bruto, vermelho_bruto, verde_bruto = dados[0], dados[1], dados[2]

    tags_base = {
        "fonte_stac": FONTES[cfg.fonte].endpoint,
        "colecao": colecao.colecao,
        "item_id": resultado.item_id,
        "data_aquisicao": resultado.data_aquisicao,
        "nuvens_percentual": resultado.nuvens_percentual,
        "bandas": resultado.bandas,
        "nivel_processamento": colecao.nivel,
        "fator_escala": colecao.escala,
        "cod_imovel": ponto.cod_imovel,
    }

    _gravar_geotiff(
        nir_bruto[np.newaxis, ...],
        grade,
        caminhos["nir"],
        nomes_bandas=[colecao.banda_nir],
        escalas=(colecao.escala,),
        tags={**tags_base, "produto": "NIR"},
    )

    grade_indice = {**grade, "nodata": float("nan")}
    for codigo, banda_extra_bruta in (
        ("ndvi", vermelho_bruto),
        ("gndvi", verde_bruto),
        ("ndwi", verde_bruto),
    ):
        indice_array = calcular_indice(nir_bruto, banda_extra_bruta, codigo)
        _gravar_geotiff(
            indice_array[np.newaxis, ...],
            grade_indice,
            caminhos[codigo],
            nomes_bandas=[INDICES[codigo].nome],
            escalas=(1.0,),
            tags={**tags_base, "produto": INDICES[codigo].nome},
        )

    resultado.crs_saida = str(grade["crs"])
    resultado.resolucao_x = abs(float(grade["transform"].a))
    resultado.resolucao_y = abs(float(grade["transform"].e))
    resultado.largura_pixels = int(grade["largura"])
    resultado.altura_pixels = int(grade["altura"])
    resultado.status = "ok"
    return resultado


def _extrair_ponto_sem_retry(
    ponto: PontoEntrada,
    cfg: ConfiguracaoExtracao,
    cancelamento: threading.Event | None,
) -> ResultadoExtracao:
    if cfg.produto == "completo":
        return _extrair_completo_ponto_sem_retry(ponto, cfg, cancelamento)
    if cfg.produto in INDICES:
        return _extrair_indice_ponto_sem_retry(ponto, cfg, cancelamento)

    colecao = obter_colecao(cfg.fonte, cfg.sensor)
    resultado = ResultadoExtracao(
        numero=ponto.numero,
        cod_imovel=ponto.cod_imovel,
        x=ponto.x,
        y=ponto.y,
        produto=cfg.produto,
        fonte=cfg.fonte,
        colecao=colecao.colecao,
    )
    caminho_saida = _caminho_saida(cfg, ponto, cfg.produto)
    resultado.caminho_saida = str(caminho_saida)

    if cancelamento and cancelamento.is_set():
        resultado.status = "cancelado"
        return resultado
    if caminho_saida.exists() and not cfg.sobrescrever:
        resultado.status = "ignorado"
        return resultado

    bbox = calcular_bbox_wgs84(ponto, cfg.buffer_metros, cfg.epsg_entrada)
    resultado.bbox_wgs84 = bbox
    bandas = (
        (colecao.banda_nir,)
        if cfg.produto == "nir"
        else colecao.bandas_rgb
    )
    itens = consultar_itens_stac(
        fonte=cfg.fonte,
        colecao=colecao.colecao,
        bbox_wgs84=bbox,
        data_inicial=cfg.data_inicial,
        data_final=cfg.data_final,
        timeout=cfg.timeout,
        tentativas=cfg.tentativas,
    )
    item = selecionar_item(
        itens=itens,
        bbox_wgs84=bbox,
        assets_necessarios=bandas,
        criterio=cfg.criterio,
        max_nuvens=cfg.max_nuvens,
    )
    propriedades = item.get("properties", {})
    resultado.item_id = str(item.get("id", ""))
    resultado.data_aquisicao = str(
        propriedades.get("datetime") or propriedades.get("start_datetime") or ""
    )
    resultado.nuvens_percentual = _percentual_nuvens(item)
    resultado.bandas = ",".join(bandas)

    assets = [
        (nome, item["assets"][nome]["href"])
        for nome in bandas
    ]
    metadados = recortar_assets(
        assets=assets,
        caminho_saida=caminho_saida,
        ponto=ponto,
        cfg=cfg,
        escala=colecao.escala,
        tags={
            "produto": cfg.produto.upper(),
            "fonte_stac": FONTES[cfg.fonte].endpoint,
            "colecao": colecao.colecao,
            "item_id": resultado.item_id,
            "data_aquisicao": resultado.data_aquisicao,
            "nuvens_percentual": resultado.nuvens_percentual,
            "bandas": resultado.bandas,
            "nivel_processamento": colecao.nivel,
            "fator_escala": colecao.escala,
            "cod_imovel": ponto.cod_imovel,
        },
    )
    resultado.crs_saida = str(metadados["crs"])
    resultado.resolucao_x, resultado.resolucao_y = metadados["resolucao"]
    resultado.largura_pixels = int(metadados["largura"])
    resultado.altura_pixels = int(metadados["altura"])
    resultado.status = "ok"
    return resultado


def _extrair_ponto(
    ponto: PontoEntrada,
    cfg: ConfiguracaoExtracao,
    cancelamento: threading.Event | None,
) -> ResultadoExtracao:
    colecao = obter_colecao(cfg.fonte, cfg.sensor)
    ultimo_erro = ""
    for tentativa in range(1, cfg.tentativas + 1):
        try:
            return _extrair_ponto_sem_retry(ponto, cfg, cancelamento)
        except Exception as exc:  # noqa: BLE001 - retry cobre rede, GDAL e STAC
            ultimo_erro = str(exc)
            if tentativa < cfg.tentativas:
                time.sleep(min(2 ** (tentativa - 1), 8))
    caminho_saida = _caminho_saida(cfg, ponto, cfg.produto)
    try:
        bbox = calcular_bbox_wgs84(ponto, cfg.buffer_metros, cfg.epsg_entrada)
    except Exception:  # noqa: BLE001 - erro original ja esta registrado
        bbox = None
    return ResultadoExtracao(
        numero=ponto.numero,
        cod_imovel=ponto.cod_imovel,
        x=ponto.x,
        y=ponto.y,
        produto=cfg.produto,
        fonte=cfg.fonte,
        colecao=colecao.colecao,
        bbox_wgs84=bbox,
        caminho_saida=str(caminho_saida),
        status="erro",
        erro=ultimo_erro,
    )


COLUNAS_MANIFESTO = [
    "numero_amostra",
    "cod_imovel",
    "x",
    "y",
    "produto",
    "fonte",
    "colecao",
    "item_id",
    "data_aquisicao",
    "nuvens_percentual",
    "bandas",
    "crs_saida",
    "resolucao_x",
    "resolucao_y",
    "largura_pixels",
    "altura_pixels",
    "bbox_lon_min",
    "bbox_lat_min",
    "bbox_lon_max",
    "bbox_lat_max",
    "caminho_saida",
    "status",
    "erro",
    "data_processamento",
]


def _registrar_manifesto(caminho: Path, resultado: ResultadoExtracao) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    novo = not caminho.exists() or caminho.stat().st_size == 0
    with caminho.open("a", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo, fieldnames=COLUNAS_MANIFESTO, delimiter=";"
        )
        if novo:
            escritor.writeheader()
        escritor.writerow(resultado.como_linha_manifesto())


def executar_extracao(
    cfg: ConfiguracaoExtracao,
    atualizar_status: StatusCallback | None = None,
    atualizar_progresso: ProgressoCallback | None = None,
    cancelamento: threading.Event | None = None,
) -> list[ResultadoExtracao]:
    """Executa lote de pontos e devolve um resultado por linha do CSV."""
    validar_configuracao(cfg)
    pontos = carregar_pontos(
        cfg.arquivo_csv, cfg.separador_csv, cfg.quantidade
    )
    cfg.pasta_saida.mkdir(parents=True, exist_ok=True)
    if cfg.produto == "completo":
        cfg = replace(cfg, pasta_imagens=proxima_pasta_imagens(cfg.pasta_saida))
    manifesto = cfg.pasta_saida / "artifacts" / "dataset_cbers_manifesto.csv"
    total = len(pontos)
    if atualizar_status:
        atualizar_status(
            f"{total} ponto(s). Fonte {FONTES[cfg.fonte].nome}; "
            f"colecao {obter_colecao(cfg.fonte, cfg.sensor).colecao}."
        )

    resultados: list[ResultadoExtracao] = []
    with ThreadPoolExecutor(
        max_workers=min(cfg.workers, total),
        thread_name_prefix="cbers",
    ) as executor:
        futuros = {
            executor.submit(_extrair_ponto, ponto, cfg, cancelamento): ponto
            for ponto in pontos
        }
        for concluido, futuro in enumerate(as_completed(futuros), start=1):
            resultado = futuro.result()
            resultados.append(resultado)
            _registrar_manifesto(manifesto, resultado)
            if atualizar_progresso:
                atualizar_progresso(concluido, total, resultado)
            if atualizar_status:
                atualizar_status(
                    f"[{concluido}/{total}] amostra {resultado.numero}: "
                    f"{resultado.status}"
                    + (f" - {resultado.erro}" if resultado.erro else "")
                )
            if cancelamento and cancelamento.is_set():
                for pendente in futuros:
                    pendente.cancel()

    resultados.sort(key=lambda resultado: resultado.numero)
    return resultados


def resumo_resultados(resultados: Iterable[ResultadoExtracao]) -> dict[str, int]:
    resumo = {"ok": 0, "erro": 0, "ignorado": 0, "cancelado": 0}
    for resultado in resultados:
        resumo[resultado.status] = resumo.get(resultado.status, 0) + 1
    return resumo


def slug_seguro(valor: str) -> str:
    """Mantido publico para integracoes que precisem nomear artefatos."""
    texto = re.sub(r"[^A-Za-z0-9._-]+", "_", valor.strip())
    return texto.strip("._") or "sem_codigo"
