package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.AdminStatisticsMapper;
import java.io.ByteArrayInputStream;
import java.time.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminStatisticsTests {
    final AdminStatisticsMapper store=mock(AdminStatisticsMapper.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AdminStatisticsService service=new AdminStatisticsService(store,admin,Clock.fixed(Instant.parse("2026-10-06T17:00:00Z"),ZoneId.of("Asia/Shanghai")));
    void data(){
        when(store.dailyUsers(any(),any(),anyString())).thenReturn(List.of(Map.of("day","2026-10-01","amount",2L)));
        when(store.dailyPublications(any(),any(),anyString())).thenReturn(List.of(Map.of("day","2026-10-07","amount",3L)));
        when(store.dailyReading(any(),any(),anyString())).thenReturn(List.of(Map.of("day","2026-10-01","millis",1001L,"readers",1L),Map.of("day","2026-10-07","millis",2999L,"readers",1L)));
        when(store.articleDistribution(anyString())).thenReturn(List.of(Map.of("status",1,"amount",3L)));
        when(store.levelDistribution(anyString())).thenReturn(List.of(Map.of("level",0,"amount",2L),Map.of("level",4,"amount",1L)));
        when(store.configuredLevels()).thenReturn(List.of(Map.of("level",0),Map.of("level",1),Map.of("level",4)));
        when(store.distinctReaders(any(),any(),anyString())).thenReturn(1L);
    }
    @Test void authorizationPrecedesEveryQuery(){
        doThrow(new BusinessException(403,"无权限")).when(admin).requirePermission(9L,"statistics.read");
        assertEquals(403,assertThrows(BusinessException.class,()->service.statistics(9L,30)).getCode());verifyNoInteractions(store);
    }
    @Test void unsupportedAndUnboundedRangesAreRejected(){
        for(int range:new int[]{-1,0,1,8,365,Integer.MAX_VALUE})assertEquals(400,assertThrows(BusinessException.class,()->service.statistics(7L,range)).getCode());
        verifyNoInteractions(store);
    }
    @Test void sourceSelectionIsValidatedBeforeAnyQuery(){for(String source:new String[]{"other","business' OR 1=1", ""})assertEquals(400,assertThrows(BusinessException.class,()->service.statistics(7L,7,source)).getCode());verifyNoInteractions(store);}
    @Test void rangeIncludesShanghaiTodayAndFillsMissingDaysWithZero(){
        data();var report=service.statistics(7L,7);
        assertEquals("2026-10-01",report.from());assertEquals("2026-10-07",report.to());assertEquals(7,report.daily().size());
        assertEquals(2,report.daily().getFirst().newUsers());assertEquals(0,report.daily().get(1).newUsers());
        assertEquals(3,report.daily().getLast().newArticles());assertEquals(0,report.daily().getLast().newUsers());
        assertEquals(2,report.periodNewUsers());assertEquals(3,report.periodNewArticles());
        assertEquals(4.0,report.periodReadingSeconds());assertEquals(1,report.periodReadingUsers());
        assertEquals(1.001,report.daily().getFirst().readingSeconds());
        assertEquals(List.of(new AdminStatisticsService.Distribution("未公开",0),new AdminStatisticsService.Distribution("已发布",3),new AdminStatisticsService.Distribution("已下架",0)),report.articles());
        assertEquals(new AdminStatisticsService.Distribution("L1",0),report.levels().get(1));
    }
    @Test void emptyDatabaseProducesValidZeroChartsAndExactRange(){
        var report=service.statistics(7L,90);assertEquals(90,report.daily().size());
        assertEquals(0,report.periodNewUsers());assertEquals(0,report.periodReadingSeconds());assertEquals(0,report.periodReadingUsers());
    }
    @Test void realEasyExcelWorkbookIsReadableAndPreservesNumbersAndEmptyDays() throws Exception {
        data();var report=service.statistics(7L,7);byte[] bytes=service.workbook(report);
        assertEquals('P',bytes[0]);assertEquals('K',bytes[1]);
        try(var workbook=new XSSFWorkbook(new ByteArrayInputStream(bytes))){
            assertEquals(4,workbook.getNumberOfSheets());
            assertEquals("统计说明",workbook.getSheetName(0));assertEquals("每日趋势",workbook.getSheetName(1));
            assertEquals("2026-10-07 01:00:00",workbook.getSheetAt(0).getRow(3).getCell(1).getStringCellValue());
            assertEquals("数据范围",workbook.getSheetAt(0).getRow(4).getCell(0).getStringCellValue());
            var daily=workbook.getSheetAt(1);assertEquals(7,daily.getLastRowNum());
            assertEquals("2026-10-01",daily.getRow(1).getCell(0).getStringCellValue());
            assertEquals(2,daily.getRow(1).getCell(1).getNumericCellValue());assertEquals(1.001,daily.getRow(1).getCell(3).getNumericCellValue());
            assertEquals(0,daily.getRow(2).getCell(1).getNumericCellValue());
            assertEquals(3,workbook.getSheetAt(2).getRow(2).getCell(1).getNumericCellValue());
            assertEquals("L1",workbook.getSheetAt(3).getRow(2).getCell(0).getStringCellValue());
        }
    }
}
