package com.easyjob.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class GatewayApplication {
    @org.springframework.context.annotation.Bean
    org.springframework.cloud.gateway.config.HttpClientCustomizer disableTransportRetry() {
        // Reactor Netty also has a transport-level retry; disable it for mutations.
        return client -> client.disableRetry(true);
    }
    public static void main(String[] args) { SpringApplication.run(GatewayApplication.class, args); }
}
