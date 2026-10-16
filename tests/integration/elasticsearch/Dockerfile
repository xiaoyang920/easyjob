FROM docker.elastic.co/elasticsearch/elasticsearch:8.15.5

# Production mappings use ik_smart / ik_max_word; match the server version.
RUN bin/elasticsearch-plugin install --batch https://get.infini.cloud/elasticsearch/analysis-ik/8.15.5
COPY src/main/resources/elasticsearch/IKAnalyzer.cfg.xml /usr/share/elasticsearch/plugins/analysis-ik/config/IKAnalyzer.cfg.xml
COPY src/main/resources/elasticsearch/easyjob-technical.dic /usr/share/elasticsearch/plugins/analysis-ik/config/custom/easyjob-technical.dic
COPY src/main/resources/elasticsearch/easyjob-synonyms.txt /usr/share/elasticsearch/config/analysis/easyjob-synonyms.txt
