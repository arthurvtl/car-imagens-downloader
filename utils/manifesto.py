# utils/manifesto.py
# Gerencia o arquivo CSV de manifesto do dataset.
# O manifesto registra cada imóvel processado com seu status, bbox, hashes e timestamp.
# Inspirado nos "tracked-artifacts" do BigEarthNet pipeline.

import csv
import os
from datetime import datetime
from pathlib import Path

COLUNAS_MANIFESTO = [
    "cod_imovel",
    "x",
    "y",
    "bbox_xmin",
    "bbox_ymin",
    "bbox_xmax",
    "bbox_ymax",
    "status_satelite",
    "status_uso_solo",
    "hash_sha256_satelite",
    "hash_sha256_uso_solo",
    "data_download",
]


def inicializar_manifesto(caminho_manifesto: str | Path) -> None:
    """
    Cria o arquivo de manifesto com o cabeçalho se ele ainda não existir.
    Não sobrescreve um manifesto existente.
    """
    caminho = Path(caminho_manifesto)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if not caminho.exists():
        with open(caminho, "w", newline="", encoding="utf-8") as arquivo_csv:
            writer = csv.DictWriter(arquivo_csv, fieldnames=COLUNAS_MANIFESTO, delimiter=";")
            writer.writeheader()


def carregar_imoveis_processados(caminho_manifesto: str | Path) -> set[str]:
    """
    Lê o manifesto e retorna um conjunto com os cod_imovel que já foram processados
    com status 'ok' em ambas as imagens. Usado para implementar downloads idempotentes.
    """
    caminho = Path(caminho_manifesto)
    imoveis_completos = set()
    if not caminho.exists():
        return imoveis_completos
    with open(caminho, "r", encoding="utf-8") as arquivo_csv:
        reader = csv.DictReader(arquivo_csv, delimiter=";")
        for linha in reader:
            if linha["status_satelite"] == "ok" and linha["status_uso_solo"] == "ok":
                imoveis_completos.add(linha["cod_imovel"])
    return imoveis_completos


def registrar_resultado(
    caminho_manifesto: str | Path,
    cod_imovel: str,
    x: float,
    y: float,
    bbox: tuple[float, float, float, float],
    status_satelite: str,
    status_uso_solo: str,
    hash_satelite: str = "",
    hash_uso_solo: str = "",
) -> None:
    """
    Acrescenta uma linha ao manifesto com o resultado do processamento de um imóvel.

    Parâmetros:
        bbox: tupla (xmin, ymin, xmax, ymax) em metros EPSG:31984
        status_*: 'ok', 'erro' ou 'pulado'
        hash_*: hash SHA256 do arquivo TIF (string vazia se não gerado)
    """
    caminho = Path(caminho_manifesto)
    linha = {
        "cod_imovel": cod_imovel,
        "x": x,
        "y": y,
        "bbox_xmin": bbox[0],
        "bbox_ymin": bbox[1],
        "bbox_xmax": bbox[2],
        "bbox_ymax": bbox[3],
        "status_satelite": status_satelite,
        "status_uso_solo": status_uso_solo,
        "hash_sha256_satelite": hash_satelite,
        "hash_sha256_uso_solo": hash_uso_solo,
        "data_download": datetime.now().isoformat(timespec="seconds"),
    }
    with open(caminho, "a", newline="", encoding="utf-8") as arquivo_csv:
        writer = csv.DictWriter(arquivo_csv, fieldnames=COLUNAS_MANIFESTO, delimiter=";")
        writer.writerow(linha)
