package com.easyjob.config;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.json.jackson.JacksonJsonpMapper;
import co.elastic.clients.transport.ElasticsearchTransport;
import co.elastic.clients.transport.rest_client.RestClientTransport;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.apache.http.HttpHost;
import org.elasticsearch.client.RestClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ElasticsearchConfig {

    @Bean
    public ElasticsearchClient elasticsearchClient() {
       RestClient restClient = RestClient.builder(
               //85.137.247.222
               new HttpHost("localhost", 9200, "http")
       ).build();
        // 2. 【核心改动】配置 Jackson 映射器，使其支持 LocalDateTime

        ObjectMapper objectMapper = new ObjectMapper();
        // 注册 Java 8 时间模块
        objectMapper.registerModule(new JavaTimeModule());
        // 如果你希望在 ES 里存的是 yyyy-MM-dd HH:mm:ss 格式，而不是 ISO 格式，可以取消注释下面这行
        objectMapper.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        ElasticsearchTransport transport = new RestClientTransport(
                restClient,new JacksonJsonpMapper(objectMapper));
        return new ElasticsearchClient(transport);
    }
}