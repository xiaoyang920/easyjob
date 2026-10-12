FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.5

# Production mappings use ik_smart / ik_max_word; match the server version.
RUN bin/elasticsearch-plugin install --batch https://get.infini.cloud/elasticsearch/analysis-ik/8.15.5
