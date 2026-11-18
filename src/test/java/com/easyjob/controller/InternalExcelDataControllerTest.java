package com.easyjob.controller;

import com.easyjob.config.ChatWebSocketHandler;
import com.easyjob.service.AdminStatisticsService;
import org.junit.jupiter.api.Test;
import org.mockito.MockedStatic;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class InternalExcelDataControllerTest {
    @Test
    void readinessRequiresTheSameServiceKeyAsTheCallback() throws Exception {
        String key = "test-key-for-excel-notification-12345";
        MockMvc mvc = MockMvcBuilders.standaloneSetup(
                new InternalExcelDataController(mock(AdminStatisticsService.class), key)).build();
        mvc.perform(get("/internal/excel/ready")).andExpect(status().isForbidden());
        mvc.perform(get("/internal/excel/ready").header("X-Excel-Key", key)).andExpect(status().isNoContent());
    }

    @Test
    void onlyTheExcelServiceCanNotifyTheJobOwner() {
        String key = "test-key-for-excel-notification-12345";
        InternalExcelDataController controller = new InternalExcelDataController(mock(AdminStatisticsService.class), key);
        UUID jobNo = UUID.randomUUID();
        InternalExcelDataController.JobFinished event = new InternalExcelDataController.JobFinished(jobNo, 42, "succeeded");
        try (MockedStatic<ChatWebSocketHandler> sockets = mockStatic(ChatWebSocketHandler.class)) {
            assertEquals(403, assertThrows(ResponseStatusException.class, () -> controller.finished("invalid", event))
                    .getStatusCode().value());
            sockets.verifyNoInteractions();
            controller.finished(key, event);
            sockets.verify(() -> ChatWebSocketHandler.sendToUser(42L, Map.of(
                    "type", "excel_export_finished", "jobNo", jobNo.toString(), "status", "succeeded")));
            sockets.verifyNoMoreInteractions();
        }
    }
}
