package com.easyjob.index;

import co.elastic.clients.elasticsearch.ElasticsearchClient;
import co.elastic.clients.json.jackson.JacksonJsonpMapper;
import co.elastic.clients.transport.rest_client.RestClientTransport;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.easyjob.agent.component.EsVectorStore;
import org.elasticsearch.client.RestClient;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.mybatis.spring.annotation.MapperScan;

import java.util.TimeZone;

@SpringBootApplication(scanBasePackages = "com.easyjob")
@MapperScan("com.easyjob.mapper")
public class SearchIndexApplication {
    public static void main(String[] args) {
        TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"));
        SpringApplication.run(SearchIndexApplication.class, args);
    }

    @Bean
    InitializingBean initializeVectorIndex(EsVectorStore vectors, BlogIndexClient blog) {
        return () -> {
            blog.checkReady();
            vectors.initIndex();
        };
    }

    @Bean
    Jackson2JsonMessageConverter indexMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    ElasticsearchClient elasticsearchClient(RestClient restClient, ObjectMapper json) {
        return new ElasticsearchClient(new RestClientTransport(restClient, new JacksonJsonpMapper(json.copy())));
    }
}
