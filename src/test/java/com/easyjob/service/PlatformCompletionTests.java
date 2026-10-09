package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import java.util.*;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
class PlatformCompletionTests {
 @Test void databasePermissionsNeverGrantUnlistedCapabilities(){var jdbc=mock(JdbcTemplate.class);var access=new ArticleAccessService(jdbc,mock(ReadingGrowthService.class),mock(RedisComponent.class),mock(ArticleIndexPublisher.class));when(jdbc.queryForList(contains("admin_role_permission"),eq(String.class),eq(7L))).thenReturn(List.of("reviews.read","reviews.manage"));assertTrue(access.hasPermission(7L,"reviews.manage"));assertFalse(access.hasPermission(7L,"users.manage"));assertFalse(access.hasPermission(7L,"made_up"));assertFalse(access.hasPermission(null,"reviews.manage"));}
 @Test void metricsPermissionAndFiltersPrecedeQueries(){var jdbc=mock(JdbcTemplate.class);var admin=mock(AdminConsoleService.class);var service=new AdminAgentMetricsService(jdbc,admin,new ObjectMapper());doThrow(new BusinessException(403,"禁止")).when(admin).requirePermission(1L,"metrics.read");assertEquals(403,assertThrows(BusinessException.class,()->service.report(1L,7,"business")).getCode());assertEquals(400,assertThrows(BusinessException.class,()->service.report(2L,365,"business")).getCode());assertEquals(400,assertThrows(BusinessException.class,()->service.report(2L,7,"bad")).getCode());verifyNoInteractions(jdbc);}
 @Test void latencyUsesNearestRankAndDoesNotTreatMissingDataAsZero(){assertEquals(0,AdminAgentMetricsService.percentile(List.of(),.95));assertEquals(200,AdminAgentMetricsService.percentile(List.of(400L,100L,200L),.5));assertEquals(400,AdminAgentMetricsService.percentile(List.of(400L,100L,200L),.95));}
 @Test void emptyMetricsHaveNoInventedSuccessRateOrLatency(){var service=new AdminAgentMetricsService(mock(JdbcTemplate.class),mock(AdminConsoleService.class),new ObjectMapper());var report=service.report(2L,7,"business");assertNull(report.get("successRate"));assertNull(report.get("activeP95Ms"));assertEquals(7,((List<?>)report.get("daily")).size());assertEquals(0L,report.get("measuredInputTokens"));}
 @Test void feedbackIsAuthenticatedAndRestrictedToKnownKinds(){var jdbc=mock(JdbcTemplate.class);var service=new RecommendationFeedbackService(jdbc);assertEquals(401,assertThrows(BusinessException.class,()->service.save(null,3L,"hide_author")).getCode());assertEquals(400,assertThrows(BusinessException.class,()->service.save(7L,3L,"like")).getCode());assertEquals(400,assertThrows(BusinessException.class,()->service.remove(7L,-1L)).getCode());verifyNoInteractions(jdbc);}
 @Test void restoringFeedbackCanOnlyDeleteTheActorsRow(){var jdbc=mock(JdbcTemplate.class);new RecommendationFeedbackService(jdbc).remove(7L,3L);verify(jdbc).update("DELETE FROM recommendation_feedback WHERE user_id=? AND article_id=?",7L,3L);}
}
