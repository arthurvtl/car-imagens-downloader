# utils/wms.py
# Funções de comunicação com o serviço WMS do GeoBases e conversão para GeoTIFF.
# Toda interação com a rede e o formato raster está isolada aqui.

import io
import time
import logging
from pathlib import Path

import numpy as np
import requests
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from PIL import Image

logger = logging.getLogger(__name__)


def calcular_bbox(x: float, y: float, buffer_metros: float) -> tuple[float, float, float, float]:
    """
    Calcula o bounding box quadrado ao redor de um ponto central.

    Parâmetros:
        x: coordenada X central em metros (EPSG:31984)
        y: coordenada Y central em metros (EPSG:31984)
        buffer_metros: metade do lado do quadrado em metros

    Retorna:
        Tupla (xmin, ymin, xmax, ymax) em metros
    """
    return (
        x - buffer_metros,
        y - buffer_metros,
        x + buffer_metros,
        y + buffer_metros,
    )


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
    """
    xmin, ymin, xmax, ymax = bbox
    return {
        "SERVICE": "WMS",
        "VERSION": wms_versao,
        "REQUEST": "GetMap",
        "LAYERS": camada,
        "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
        "WIDTH": largura_pixels,
        "HEIGHT": altura_pixels,
        "SRS": srid,
        "FORMAT": formato,
        "TRANSPARENT": transparente,
    }


def requisitar_imagem_wms(
    wms_url: str,
    parametros: dict,
    timeout: int,
    tentativas: int,
    pausa_entre_tentativas: int,
) -> bytes:
    """
    Realiza a requisição HTTP ao endpoint WMS e retorna o conteúdo binário da imagem.
    Em caso de falha de rede, retenta até `tentativas` vezes com pausa entre elas.

    Levanta:
        RuntimeError se todas as tentativas falharem.
    """
    for numero_tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.get(wms_url, params=parametros, timeout=timeout)
            resposta.raise_for_status()

            # Verificar se o servidor retornou uma imagem (não uma mensagem de erro XML)
            tipo_conteudo = resposta.headers.get("Content-Type", "")
            if "xml" in tipo_conteudo or "html" in tipo_conteudo:
                raise RuntimeError(
                    f"Servidor retornou erro ao invés de imagem: {resposta.text[:300]}"
                )

            return resposta.content

        except (requests.RequestException, RuntimeError) as erro:
            logger.warning(
                f"Tentativa {numero_tentativa}/{tentativas} falhou: {erro}"
            )
            if numero_tentativa < tentativas:
                time.sleep(pausa_entre_tentativas)

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
    Converte o conteúdo binário recebido do WMS em um GeoTIFF georreferenciado.

    O GeoTIFF resultante contém:
    - 3 bandas RGB (uint8)
    - CRS definido pelo epsg_codigo
    - Transform afim derivado do bbox (posição geográfica real de cada pixel)

    Parâmetros:
        conteudo_binario: bytes retornados diretamente da resposta HTTP do WMS
        caminho_saida: caminho completo onde o arquivo .tif será gravado
        bbox: (xmin, ymin, xmax, ymax) em metros
        largura_pixels: largura da imagem em pixels (deve ser 1024)
        altura_pixels: altura da imagem em pixels (deve ser 1024)
        epsg_codigo: código numérico do CRS (ex: 31984)
    """
    caminho = Path(caminho_saida)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    # Decodificar o conteúdo binário em array numpy via Pillow
    imagem_pil = Image.open(io.BytesIO(conteudo_binario)).convert("RGB")
    array_imagem = np.array(imagem_pil)  # shape: (altura, largura, 3)

    # Calcular a transformação afim a partir do bbox
    # from_bounds(west, south, east, north, width, height)
    xmin, ymin, xmax, ymax = bbox
    transform_afim = from_bounds(xmin, ymin, xmax, ymax, largura_pixels, altura_pixels)

    crs = CRS.from_epsg(epsg_codigo)

    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        height=altura_pixels,
        width=largura_pixels,
        count=3,           # 3 bandas: R, G, B
        dtype="uint8",
        crs=crs,
        transform=transform_afim,
        compress="lzw",
    ) as dataset_raster:
        # rasterio espera shape (bandas, altura, largura) — transpor o array numpy
        dataset_raster.write(array_imagem.transpose(2, 0, 1))


def baixar_imagem(
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
    Função de alto nível: realiza o download completo de uma imagem WMS e a salva
    como GeoTIFF georreferenciado. Combina montar_parametros_wms,
    requisitar_imagem_wms e salvar_como_geotiff.
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
    conteudo = requisitar_imagem_wms(
        wms_url=wms_url,
        parametros=parametros,
        timeout=timeout,
        tentativas=tentativas,
        pausa_entre_tentativas=pausa_entre_tentativas,
    )
    salvar_como_geotiff(
        conteudo_binario=conteudo,
        caminho_saida=caminho_saida,
        bbox=bbox,
        largura_pixels=largura_pixels,
        altura_pixels=altura_pixels,
        epsg_codigo=epsg_codigo,
    )
