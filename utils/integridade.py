# utils/integridade.py
# Funções para verificar integridade de arquivos via hash SHA256.
# Inspirado na prática do BigEarthNet pipeline de rastrear hashes de cada arquivo gerado.

import hashlib
from pathlib import Path


def calcular_hash_sha256(caminho_arquivo: str | Path) -> str:
    """
    Calcula e retorna o hash SHA256 do conteúdo binário de um arquivo.
    Lê o arquivo em blocos para não carregar arquivos grandes inteiros na memória.
    """
    hash_sha256 = hashlib.sha256()
    with open(caminho_arquivo, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(8192), b""):
            hash_sha256.update(bloco)
    return hash_sha256.hexdigest()


def verificar_arquivo_integro(caminho_arquivo: str | Path, hash_esperado: str) -> bool:
    """
    Retorna True se o hash SHA256 do arquivo bate com o hash_esperado.
    Retorna False se o arquivo não existe ou se o hash diverge.
    """
    caminho = Path(caminho_arquivo)
    if not caminho.exists():
        return False
    return calcular_hash_sha256(caminho) == hash_esperado
