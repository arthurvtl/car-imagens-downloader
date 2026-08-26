"""Interface de linha de comando do extrator CBERS."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from utils.cbers import (
    FONTES,
    INDICES,
    SENSORES,
    ConfiguracaoExtracao,
    ErroCBERS,
    executar_extracao,
    obter_colecao,
    pixels_para_resolucao,
    resumo_resultados,
    sensores_disponiveis,
)


def _produto(valor: str) -> str:
    normalizado = valor.strip().lower()
    aliases = {
        "nir": "nir",
        "infravermelho": "nir",
        "rgb": "rgb",
        "colorida": "rgb",
        "visivel": "rgb",
        "visível": "rgb",
        "completo": "completo",
        "3bandas": "completo",
        "tudo": "completo",
        **{codigo: codigo for codigo in INDICES},
    }
    if normalizado not in aliases:
        raise argparse.ArgumentTypeError(
            "use nir/infravermelho, rgb/colorida, completo/tudo "
            f"(baixa 3 bandas e calcula os 3 indices) ou um indice "
            f"({', '.join(INDICES)})"
        )
    return aliases[normalizado]


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extrator-cbers",
        description=(
            "Baixa recortes CBERS NIR ou RGB para pontos de um CSV "
            "usando STAC e GeoTIFF/COG."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="CSV com colunas cod_imovel;x;y.",
    )
    parser.add_argument(
        "--caminho",
        type=Path,
        help="Pasta onde NIR/RGB e artifacts serao criados.",
    )
    parser.add_argument(
        "--produto",
        type=_produto,
        default="nir",
        help=(
            "nir/infravermelho, rgb/colorida, ou um indice espectral "
            f"({', '.join(INDICES)}) - baixa NIR + a banda necessaria e ja "
            "calcula o indice."
        ),
    )
    parser.add_argument(
        "--fonte",
        choices=sorted(FONTES),
        default="inpe",
        help="Endpoint STAC usado para busca e download.",
    )
    parser.add_argument(
        "--sensor",
        choices=sorted(SENSORES),
        default="wpm",
        help="Camera/colecao CBERS.",
    )
    parser.add_argument(
        "--data-inicial",
        default="2024-01-01",
        help="Inicio do periodo, AAAA-MM-DD.",
    )
    parser.add_argument(
        "--data-final",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Fim do periodo, AAAA-MM-DD.",
    )
    parser.add_argument(
        "--buffer",
        type=float,
        default=1024,
        help="Metade do lado do recorte, em metros.",
    )
    parser.add_argument(
        "--epsg-entrada",
        default="EPSG:31984",
        help="CRS das colunas x e y.",
    )
    parser.add_argument(
        "--separador",
        default=";",
        help="Separador do CSV.",
    )
    parser.add_argument(
        "--criterio",
        choices=("menor-nuvem", "mais-recente"),
        default="menor-nuvem",
        help="Como escolher quando ha varias cenas.",
    )
    parser.add_argument(
        "--max-nuvens",
        type=float,
        help="Descarta cenas com percentual conhecido acima deste valor.",
    )
    parser.add_argument(
        "--largura",
        type=int,
        help="Largura em pixels; omita junto com altura para resolucao nativa.",
    )
    parser.add_argument(
        "--altura",
        type=int,
        help="Altura em pixels; omita junto com largura para resolucao nativa.",
    )
    parser.add_argument(
        "--resolucao-m",
        type=float,
        help=(
            "Metros por pixel desejados (ex: 2 para 2m/pixel). Calcula "
            "largura/altura a partir do buffer automaticamente; nao "
            "combinar com --largura/--altura."
        ),
    )
    parser.add_argument(
        "--qtd",
        type=int,
        help="Processa apenas as primeiras N linhas.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Pontos processados em paralelo.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Timeout de rede em segundos.",
    )
    parser.add_argument(
        "--tentativas",
        type=int,
        default=3,
        help="Tentativas por ponto.",
    )
    parser.add_argument(
        "--sobrescrever",
        action="store_true",
        help="Substitui arquivos existentes.",
    )
    parser.add_argument(
        "--listar-opcoes",
        action="store_true",
        help="Lista endpoints, sensores e colecoes.",
    )
    return parser


def _listar_opcoes() -> None:
    for codigo_fonte, fonte in FONTES.items():
        print(f"{codigo_fonte}: {fonte.nome}")
        print(f"  endpoint: {fonte.endpoint}")
        for sensor in sensores_disponiveis(codigo_fonte):
            colecao = obter_colecao(codigo_fonte, sensor.codigo)
            print(
                f"  {sensor.codigo}: {sensor.nome} | {colecao.colecao} | "
                f"NIR={colecao.banda_nir} | RGB={','.join(colecao.bandas_rgb)}"
            )


def _configuracao(args: argparse.Namespace) -> ConfiguracaoExtracao:
    if args.csv is None or args.caminho is None:
        raise ErroCBERS("--csv e --caminho sao obrigatorios.")

    largura, altura = args.largura, args.altura
    if args.resolucao_m is not None:
        if largura is not None or altura is not None:
            raise ErroCBERS(
                "--resolucao-m nao pode ser combinado com --largura/--altura."
            )
        largura, altura = pixels_para_resolucao(args.buffer, args.resolucao_m)

    return ConfiguracaoExtracao(
        arquivo_csv=args.csv.expanduser().resolve(),
        pasta_saida=args.caminho.expanduser().resolve(),
        produto=args.produto,
        fonte=args.fonte,
        sensor=args.sensor,
        data_inicial=args.data_inicial,
        data_final=args.data_final,
        buffer_metros=args.buffer,
        epsg_entrada=args.epsg_entrada,
        separador_csv=args.separador,
        criterio=args.criterio,
        max_nuvens=args.max_nuvens,
        largura_pixels=largura,
        altura_pixels=altura,
        quantidade=args.qtd,
        workers=args.workers,
        timeout=args.timeout,
        tentativas=args.tentativas,
        sobrescrever=args.sobrescrever,
    )


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    if args.listar_opcoes:
        _listar_opcoes()
        return 0

    try:
        cfg = _configuracao(args)
        resolucao = (
            f"{(2 * cfg.buffer_metros) / cfg.largura_pixels:g} m/pixel"
            if cfg.largura_pixels
            else "nativa do sensor"
        )
        print(
            f"Produto={cfg.produto.upper()} | fonte={cfg.fonte} | "
            f"sensor={cfg.sensor} | buffer={cfg.buffer_metros:g} m | "
            f"resolucao={resolucao}"
        )

        def progresso(concluido, total, resultado):
            detalhe = f" | {resultado.item_id}" if resultado.item_id else ""
            print(
                f"[{concluido}/{total}] amostra {resultado.numero}: "
                f"{resultado.status}{detalhe}",
                flush=True,
            )

        resultados = executar_extracao(
            cfg,
            atualizar_status=None,
            atualizar_progresso=progresso,
        )
    except (ErroCBERS, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130

    resumo = resumo_resultados(resultados)
    print(
        "Concluido: "
        f"{resumo['ok']} ok, {resumo['ignorado']} ignorado(s), "
        f"{resumo['erro']} erro(s), {resumo['cancelado']} cancelado(s)."
    )
    print(f"Saida: {cfg.pasta_saida}")
    return 1 if resumo["erro"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
