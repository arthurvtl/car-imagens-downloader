# configuracoes.py
# Ponto central de configuração do pipeline IntegraCar.
# Edite este arquivo para adaptar a outras camadas, tamanhos ou bases de dados.

CONFIGURACOES = {
    # --- Fonte de dados ---
    "wms_url": "https://ide.geobases.es.gov.br/geoserver/ows",
    "wms_versao": "1.1.1",

    # Typenames das camadas no GeoBases — confirmar no QGIS antes de executar
    "camada_satelite": "geonode:PREENCHER_TYPENAME_KOMPSAT",
    "camada_uso_solo": "geonode:PREENCHER_TYPENAME_IJSN_USO_SOLO",

    # --- Sistema de referência ---
    "srid_wms": "EPSG:31984",       # SRS usado na requisição WMS
    "epsg_codigo": 31984,           # Código numérico para gravar no GeoTIFF com rasterio

    # --- Dimensões do recorte ---
    # buffer_metros define metade do lado do quadrado recortado ao redor do ponto central.
    # Com buffer=512 e 1024 pixels → resolução de 1m/pixel (compatível com KOMPSAT ~1m).
    "buffer_metros": 1024,
    "largura_pixels": 2048,
    "altura_pixels": 2048,

    # --- Formato da requisição WMS ---
    "formato_wms": "image/tiff",    # Solicitar diretamente em TIFF ao GeoServer
    "transparente": "FALSE",

    # --- Saídas ---
    "pasta_saida": "saida",
    "pasta_artifacts": "artifacts",
    "pasta_logs": "logs",
    "nome_arquivo_satelite": "satelite.tif",
    "nome_arquivo_uso_solo": "uso_solo.tif",
    "nome_manifesto": "dataset_manifesto.csv",
    "nome_log": "execucao.log",

    # --- Entrada ---
    "arquivo_csv": "coordenadas_treino_amostra.csv",
    "separador_csv": ";",

    # --- Comportamento do pipeline ---
    "pular_se_existir": True,       # Se True, pula imóveis que já têm os dois TIFs no disco
    "workers_paralelos": 4,         # Número de downloads simultâneos (cuidado com rate limit)
    "timeout_requisicao": 60,       # Segundos de timeout por requisição WMS
    "tentativas_por_imagem": 3,     # Número de retentativas em caso de falha de rede
    "pausa_entre_tentativas": 5,    # Segundos de espera entre retentativas
}
