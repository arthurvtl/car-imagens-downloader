# configuracoes.py
# Ponto central de configuração do pipeline IntegraCar.
# Edite este arquivo para adaptar a outras camadas, tamanhos ou bases de dados.

CONFIGURACOES = {
    # --- Fonte de dados ---
    "wms_url": "https://ide.geobases.es.gov.br/geoserver/ows",
    "wms_versao": "1.3.0",

    # Typenames das camadas no GeoBases (confirmados no catálogo ide.geobases.es.gov.br)
    "camada_satelite": "geonode:ijsn-ortofotomosaico-es-kompsat-3-3a-2019-2020",
    "camada_uso_solo": "geonode:ijsn_map_uso_solo_es_2019_20200",

    # --- Sistema de referência ---
    # WMS 1.3.0 com EPSG:4326 exige bbox em ordem lat/lon (invertida)
    # As coordenadas do CSV estão em EPSG:31984 (UTM 24S) e serão convertidas para EPSG:4326
    "srid_entrada": "EPSG:31984",     # CRS das coordenadas no CSV
    "srid_wms": "EPSG:4326",          # CRS usado na requisição WMS (lat/lon)
    "epsg_codigo_saida": 4326,        # Código numérico para gravar no GeoTIFF

    # --- Dimensões do recorte ---
    # buffer_metros define metade do lado do quadrado recortado ao redor do ponto central.
    # Com buffer=1024 e 2048 pixels → resolução de 1m/pixel (compatível com KOMPSAT ~1m).
    "buffer_metros": 512,
    "largura_pixels": 1024,
    "altura_pixels": 1024,

    # --- Formato da requisição WMS ---
    "formato_wms": "image/png",      # PNG é mais compatível com WMS do GeoBases
    "transparente": "FALSE",

    # --- Saídas ---
    # Duas pastas separadas: SEM COR (satélite bruto) e COM COR (uso do solo colorido)
    "pasta_saida": "saida",
    "nome_pasta_sem_cor": "SEM COR",
    "nome_pasta_com_cor": "COM COR",
    "prefixo_arquivo": "amostra",       # Gera amostra_1.tif, amostra_2.tif, ...
    "pasta_artifacts": "artifacts",
    "pasta_logs": "logs",
    "nome_manifesto": "dataset_manifesto.csv",
    "nome_log": "execucao.log",

    # --- Entrada ---
    "arquivo_csv": "coordenadas_treino_amostra.csv",
    "separador_csv": ";",

    # --- Comportamento do pipeline ---
    "workers_paralelos": 4,         # Número de amostras baixadas em paralelo
    "timeout_requisicao": 60,       # Segundos de timeout por requisição WMS
    "tentativas_por_imagem": 3,     # Número de retentativas em caso de falha de rede
    "pausa_entre_tentativas": 2,    # Segundos de espera entre retentativas
}
