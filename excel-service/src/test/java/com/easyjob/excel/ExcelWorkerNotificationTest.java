package com.easyjob.excel;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.net.InetSocketAddress;
import java.nio.file.Path;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ExcelWorkerNotificationTest {
    private static final String KEY = "test-key-for-excel-notification-12345";
    @TempDir Path output;

    @Test
    void sendsOnlyTheExhaustedJobThisWorkerUpdatedAndContinuesAfterCallbackFailure() throws Exception {
        String winner = UUID.randomUUID().toString();
        String other = UUID.randomUUID().toString();
        ExcelJobMapper jobs = mock(ExcelJobMapper.class);
        when(jobs.exhaustedCandidates(3)).thenReturn(List.of(expired(winner), expired(other)));
        when(jobs.exhaust(winner, 3)).thenReturn(1);
        when(jobs.exhaust(other, 3)).thenReturn(0);
        when(jobs.candidates(3)).thenReturn(List.of());
        ObjectMapper json = new ObjectMapper();
        AtomicReference<JsonNode> body = new AtomicReference<>();
        AtomicReference<String> key = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/excel/job-finished", exchange -> {
            body.set(json.readTree(exchange.getRequestBody()));
            key.set(exchange.getRequestHeaders().getFirst("X-Excel-Key"));
            exchange.sendResponseHeaders(503, -1);
            exchange.close();
        });
        server.start();
        try {
            ExcelWorker worker = new ExcelWorker(jobs, "http://127.0.0.1:" + server.getAddress().getPort(), KEY, output, 10);
            worker.scan();
            assertEquals(KEY, key.get());
            assertEquals(winner, body.get().path("jobNo").asText());
            assertEquals(42, body.get().path("ownerId").asLong());
            assertEquals("failed", body.get().path("status").asText());
            verify(jobs).candidates(3);
        } finally {
            server.stop(0);
        }
    }

    private static ExcelJob expired(String jobNo) {
        LocalDate from = LocalDate.of(2026, 1, 1);
        return new ExcelJob(jobNo, 42, 7, "business", from, from.plusDays(6),
                "running", 3, null, null, null);
    }
}
