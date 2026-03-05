# utils/wms.py
# Funções de comunicação com o serviço WMS do GeoBases e conversão para GeoTIFF.


import io
import asyncio
import logging
from pathlib import Path

import numpy as np
import aiohttp
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from PIL import Image
from owslib.wms import WebMapService
from pyproj import Transformer

logger = logging.getLogger(__name__)

# Cache global da conexão WMS (evita reconectar a cada imagem)
_conexao_wms = None


def conectar_wms(wms_url: str, wms_versao: str) -> WebMapService:
    """
    Conecta ao serviço WMS do GeoBases e retorna o objeto de conexão.
    Usa cache para não reconectar a cada requisição.
    """
    global _conexao_wms
    if _conexao_wms is not None:
        return _conexao_wms

    logger.info(f"Conectando ao serviço WMS: {wms_url}")
    _conexao_wms = WebMapService(wms_url, version=wms_versao)
    total_camadas = len(list(_conexao_wms.contents))
    logger.info(f"Conectado com sucesso. Camadas disponíveis: {total_camadas}")
    return _conexao_wms


def validar_camada(wms: WebMapService, nome_camada: str) -> bool:
    """
    Verifica se a camada existe no serviço WMS.
    """
    return nome_camada in wms.contents


# Cache do transformador de coordenadas (evita recriar a cada chamada)
_transformador_cache = {}


def _obter_transformador(srid_entrada: str) -> Transformer:
    """Retorna transformador de coordenadas com cache."""
    if srid_entrada not in _transformador_cache:
        _transformador_cache[srid_entrada] = Transformer.from_crs(
            srid_entrada, "EPSG:4326", always_xy=True
        )
    return _transformador_cache[srid_entrada]


def calcular_bbox_latlon(
    x: float, y: float, buffer_metros: float, srid_entrada: str
) -> tuple[float, float, float, float]:
    """
    Calcula o bounding box em coordenadas geográficas (lat/lon) a partir de
    um ponto central em UTM.

    Parâmetros:
        x: coordenada X central em metros (UTM)
        y: coordenada Y central em metros (UTM)
        buffer_metros: metade do lado do quadrado em metros
        srid_entrada: CRS de entrada (ex: "EPSG:31984")

    Retorna:
        Tupla (minx_lon, miny_lat, maxx_lon, maxy_lat) em graus decimais
    """
    # Bbox em UTM (metros)
    xmin_utm = x - buffer_metros
    ymin_utm = y - buffer_metros
    xmax_utm = x + buffer_metros
    ymax_utm = y + buffer_metros

    # Converter cantos para lat/lon usando transformador cachado
    transformador = _obter_transformador(srid_entrada)
    lon_min, lat_min = transformador.transform(xmin_utm, ymin_utm)
    lon_max, lat_max = transformador.transform(xmax_utm, ymax_utm)

    return (lon_min, lat_min, lon_max, lat_max)


def montar_parametros_wms(
    camada: str,
    bbox: tuple[float, float, float, float],
    largura_pixels: int,
    altura_pixels: int,
    srid: str,
    wms_versao: str,
    formato: str,
    transparente: str,
) -> dict:
    """
    Monta o dicionário de parâmetros para uma requisição WMS GetMap.

    IMPORTANTE: WMS 1.3.0 com EPSG:4326 usa ordem lat/lon (invertida).
    """
    minx_lon, miny_lat, maxx_lon, maxy_lat = bbox

    # WMS 1.3.0 com EPSG:4326: inverte para lat,lon
    bbox_str = f"{miny_lat},{minx_lon},{maxy_lat},{maxx_lon}"

    return {
        "service": "WMS",
        "version": wms_versao,
        "request": "GetMap",
        "layers": camada,
        "bbox": bbox_str,
        "width": largura_pixels,
        "height": altura_pixels,
        "crs": srid,
        "format": formato,
        "styles": "",
    }


async def requisitar_imagem_wms_async(
    sessao: aiohttp.ClientSession,
    wms_url: str,
    parametros: dict,
    timeout: int,
    tentativas: int,
    pausa_entre_tentativas: int,
) -> bytes:
    """
    Realiza a requisição HTTP assíncrona ao endpoint WMS usando aiohttp.
    Em caso de falha, retenta até `tentativas` vezes com pausa entre elas.
    """
    timeout_cfg = aiohttp.ClientTimeout(total=timeout)

    for numero_tentativa in range(1, tentativas + 1):
        try:
            async with sessao.get(
                wms_url, params=parametros, timeout=timeout_cfg
            ) as resposta:
                resposta.raise_for_status()

                # Verificar se o servidor retornou uma imagem
                tipo_conteudo = resposta.headers.get("Content-Type", "")
                if "xml" in tipo_conteudo or "text" in tipo_conteudo:
                    corpo = await resposta.text()
                    raise RuntimeError(
                        f"Servidor retornou erro ao invés de imagem: {corpo[:300]}"
                    )

                return await resposta.read()

        except asyncio.TimeoutError:
            logger.warning(f"Timeout na tentativa {numero_tentativa}/{tentativas}")
            if numero_tentativa < tentativas:
                await asyncio.sleep(pausa_entre_tentativas)

        except (aiohttp.ClientError, RuntimeError) as erro:
            logger.warning(
                f"Tentativa {numero_tentativa}/{tentativas} falhou: {erro}"
            )
            if numero_tentativa < tentativas:
                await asyncio.sleep(pausa_entre_tentativas)

    raise RuntimeError(f"Todas as {tentativas} tentativas falharam para a requisição WMS.")


def salvar_como_geotiff(
    conteudo_binario: bytes,
    caminho_saida: str | Path,
    bbox: tuple[float, float, float, float],
    largura_pixels: int,
    altura_pixels: int,
    epsg_codigo: int,
) -> None:
    """
    Converte o conteúdo binário recebido do WMS (PNG) em um GeoTIFF georreferenciado.
    """
    caminho = Path(caminho_saida)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    # Decodificar o conteúdo binário em array numpy via Pillow
    imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
    array_imagem = np.array(imagem_pil)  # shape: (altura, largura, 3)

    # Calcular a transformação afim a partir do bbox
    minx, miny, maxx, maxy = bbox
    transform_afim = from_bounds(minx, miny, maxx, maxy, largura_pixels, altura_pixels)

    crs = CRS.from_epsg(epsg_codigo)

    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        height=altura_pixels,
        width=largura_pixels,
        count=3,
        dtype="uint8",
        crs=crs,
        transform=transform_afim,
        compress="lzw",
    ) as dataset_raster:
        dataset_raster.write(array_imagem.transpose(2, 0, 1))


async def baixar_imagem_async(
    sessao: aiohttp.ClientSession,
    wms_url: str,
    camada: str,
    bbox: tuple[float, float, float, float],
    caminho_saida: str | Path,
    largura_pixels: int,
    altura_pixels: int,
    srid: str,
    wms_versao: str,
    formato: str,
    transparente: str,
    epsg_codigo: int,
    timeout: int,
    tentativas: int,
    pausa_entre_tentativas: int,
) -> None:
    """
    Função de alto nível assíncrona: realiza o download completo de uma imagem WMS
    e a salva como GeoTIFF georreferenciado.
    """
    parametros = montar_parametros_wms(
        camada=camada,
        bbox=bbox,
        largura_pixels=largura_pixels,
        altura_pixels=altura_pixels,
        srid=srid,
        wms_versao=wms_versao,
        formato=formato,
        transparente=transparente,
    )
    conteudo = await requisitar_imagem_wms_async(
        sessao=sessao,
        wms_url=wms_url,
        parametros=parametros,
        timeout=timeout,
        tentativas=tentativas,
        pausa_entre_tentativas=pausa_entre_tentativas,
    )
    # salvar_como_geotiff é CPU-bound (Pillow + rasterio), roda no executor de threads
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        salvar_como_geotiff,
        conteudo,
        caminho_saida,
        bbox,
        largura_pixels,
        altura_pixels,
        epsg_codigo,
    )
