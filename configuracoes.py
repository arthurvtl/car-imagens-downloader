# configuracoes.py
# Ponto central de configuração do pipeline IntegraCar.
#
# ⚠️  Na maioria dos casos você NÃO precisa editar este arquivo.
#     Use os argumentos da linha de comando em extrator.py:
#
#     python extrator.py --csv MEU_ARQUIVO.csv --caminho ./saida
#     python extrator.py --help
#
# Este arquivo contém apenas os valores padrão e configurações
# que raramente mudam (URLs do servidor, layers WMS, etc.).

CONFIGURACOES = {
    # --- Fonte de dados WMS ---
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

    # --- Dimensões padrão do recorte ---
    # Podem ser sobrescritas via: --buffer, --largura, --altura
    "buffer_metros": 1024,    # Metade do lado do quadrado em metros
    "largura_pixels": 1024,   # Largura da imagem de saída
    "altura_pixels": 1024,    # Altura da imagem de saída

    # --- Formato da requisição WMS ---
    "formato_wms": "image/png",      # PNG é mais compatível com WMS do GeoBases
    "transparente": "FALSE",

    # --- Saídas internas (não alteráveis via CLI) ---
    "prefixo_arquivo": "amostra",        # Gera amostra_1.tif, amostra_2.tif, ...
    "pasta_artifacts": "artifacts",
    "pasta_logs": "logs",
    "nome_manifesto": "dataset_manifesto.csv",
    "nome_log": "execucao.log",

    # --- Entrada padrão do CSV ---
    "separador_csv": ";",

    # --- Comportamento do pipeline ---
    "workers_paralelos": 4,         # Número de amostras baixadas em paralelo
    "timeout_requisicao": 60,       # Segundos de timeout por requisição WMS
    "tentativas_por_imagem": 3,     # Número de retentativas em caso de falha de rede
    "pausa_entre_tentativas": 2,    # Segundos de espera entre retentativas

    # --- Processamento offline 2012 ---
    # URL oficial do shapefile de uso e cobertura vegetal 2012-2015
    "url_shapefile_2012": "https://one.s3.es.gov.br/pr-geobases-public/MAP_ES_2012_2015/MAP_ES_2012_2015_USO_COBERTURA_VEGETAL_2012-2015.zip",
    # Pasta temporária onde o ZIP será extraído para o processamento de 2012
    "pasta_temp_shapefile": "temp_shp_2012",

    # Camada WMS do ortofotomosaico 2012-2015
    "camada_satelite_2012": "geonode:iema_ortofotomosaico_es_025m_2012-2015",
}
