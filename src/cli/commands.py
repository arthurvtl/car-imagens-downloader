"""
src.cli.commands
Interface de linha de comando do pipeline multi-satélite.

Uso:
  python main.py run --csv coords.csv --satellite sentinel --cloud 20 --layer true
  python main.py list-satellites
  python main.py gui
"""

from __future__ import annotations

import argparse
import sys

from src.core.config import load_config
from src.satellites.registry import list_satellites


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        prog="integracar",
        description="Pipeline multi-satélite IntegraCar — Download de imagens geoespaciais",
    )
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponíveis")

    # --- Comando: run ---
    run_parser = subparsers.add_parser("run", help="Executa o pipeline de download")
    run_parser.add_argument(
        "--csv", required=True,
        help="Caminho para o arquivo CSV de coordenadas",
    )
    run_parser.add_argument(
        "--output", "-o", default="saida",
        help="Pasta de saída (padrão: saida)",
    )
    run_parser.add_argument(
        "--satellite", "-s", default="kompsat",
        choices=list_satellites(),
        help="Satélite a utilizar (padrão: kompsat)",
    )
    run_parser.add_argument(
        "--cloud", type=int, default=20,
        help="Cobertura máxima de nuvens em %% (padrão: 20)",
    )
    run_parser.add_argument(
        "--layer", type=str, default="false",
        choices=["true", "false"],
        help="Baixar camada segmentada (padrão: false)",
    )
    run_parser.add_argument(
        "--buffer", type=int, default=None,
        help="Buffer em metros (padrão: config.yaml)",
    )
    run_parser.add_argument(
        "--width", type=int, default=None,
        help="Largura em pixels (padrão: config.yaml)",
    )
    run_parser.add_argument(
        "--height", type=int, default=None,
        help="Altura em pixels (padrão: config.yaml)",
    )
    run_parser.add_argument(
        "--workers", type=int, default=None,
        help="Número de workers paralelos (padrão: config.yaml)",
    )
    run_parser.add_argument(
        "--limit", type=int, default=None,
        help="Limitar a N primeiras coordenadas",
    )
    run_parser.add_argument(
        "--date-start", default=None,
        help="Data inicial YYYY-MM-DD (padrão: config.yaml)",
    )
    run_parser.add_argument(
        "--date-end", default=None,
        help="Data final YYYY-MM-DD (padrão: config.yaml)",
    )
    run_parser.add_argument(
        "--config", default=None,
        help="Caminho para arquivo config.yaml alternativo",
    )

    # --- Comando: list-satellites ---
    subparsers.add_parser(
        "list-satellites",
        help="Lista satélites suportados",
    )

    # --- Comando: gui ---
    subparsers.add_parser("gui", help="Abre a interface gráfica (Tkinter)")

    return parser


def cmd_run(args: argparse.Namespace) -> None:
    """Executa o pipeline via CLI."""
    from src.core.pipeline import run_pipeline

    config = load_config(args.config)

    config.arquivo_csv = args.csv
    config.pasta_saida = args.output
    config.satellite_name = args.satellite
    config.cloud_cover_max = args.cloud
    config.download_segmentada = args.layer.lower() == "true"
    config.limite_amostras = args.limit

    if args.buffer is not None:
        config.buffer_metros = args.buffer
    if args.width is not None:
        config.largura_pixels = args.width
    if args.height is not None:
        config.altura_pixels = args.height
    if args.workers is not None:
        config.workers_paralelos = args.workers
    if args.date_start is not None:
        config.date_start = args.date_start
    if args.date_end is not None:
        config.date_end = args.date_end

    result = run_pipeline(config)

    print(f"\nResultado: {result['sucesso']} sucesso, {result['erro']} erro, {result['total']} total")


def cmd_list_satellites() -> None:
    """Lista satélites suportados."""
    config = load_config()
    print("\nSatélites suportados:")
    print("-" * 50)
    for name in list_satellites():
        sat = config.satellites.get(name)
        if sat:
            print(f"  {name:<12} {sat.type:<6} {sat.description}")
        else:
            print(f"  {name:<12} (configuração ausente)")
    print()


def cmd_gui() -> None:
    """Abre a GUI Tkinter."""
    from src.gui.app import main_gui
    main_gui()


def main() -> None:
    """Ponto de entrada principal da CLI."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "list-satellites":
        cmd_list_satellites()
    elif args.command == "gui":
        cmd_gui()
    else:
        parser.print_help()
