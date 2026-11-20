package com.easyjob.agent.config;

import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import java.time.Duration;

@Getter
@Setter
@ConfigurationProperties(prefix = "agent.embedding.execution")
public class EmbeddingExecutionProperties {
    private int corePoolSize = 8;
    private int maxPoolSize = 8;
    private int queueCapacity = 16;
    private int keepAliveSeconds = 60;
    private int perArticleParallelism = 4;
    private int batchSize = 16;
    private Duration articleTimeout = Duration.ofSeconds(120);

    public void validate() {
        if (corePoolSize < 1 || maxPoolSize < corePoolSize || maxPoolSize > 32
                || queueCapacity < 0 || queueCapacity > 128
                || keepAliveSeconds < 1 || keepAliveSeconds > 3600
                || perArticleParallelism < 1 || perArticleParallelism > 32
                || perArticleParallelism > maxPoolSize + queueCapacity
                || batchSize < 1 || batchSize > 16
                || articleTimeout == null || articleTimeout.isNegative() || articleTimeout.isZero()
                || articleTimeout.compareTo(Duration.ofMinutes(10)) > 0) {
            throw new IllegalArgumentException("Invalid agent.embedding.execution configuration");
        }
    }
}
