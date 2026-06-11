FROM docker.elastic.co/elasticsearch/elasticsearch:8.10.0
RUN elasticsearch-plugin install -b https://get.infini.cloud/elasticsearch/analysis-ik/8.10.0
