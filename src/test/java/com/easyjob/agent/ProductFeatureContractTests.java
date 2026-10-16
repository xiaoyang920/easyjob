package com.easyjob.agent;
import com.easyjob.controller.ArticleController;
import com.easyjob.service.ArticleService;
import com.easyjob.dto.ArticleCreateDTO;
import com.easyjob.vo.ArticleDetailVO;
import com.easyjob.agent.controller.AgentFeaturesController;
import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.service.AdminConsoleService;
import com.easyjob.utils.UserContext;
import com.easyjob.exception.BusinessException;
import org.junit.jupiter.api.*;
import org.springframework.test.util.ReflectionTestUtils;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class ProductFeatureContractTests {
    @AfterEach void clear(){UserContext.clear();}
    @Test void firstDraftSaveReturnsTheRevisionIdentityAndLockForNextAutosave(){
        var articles=mock(ArticleService.class);var controller=new ArticleController();
        ReflectionTestUtils.setField(controller,"articleService",articles);
        var dto=new ArticleCreateDTO();var detail=new ArticleDetailVO();detail.setArticleId("42");detail.setRevisionId("10");detail.setLockVersion(0L);
        when(articles.saveArticle(dto)).thenReturn(42L);when(articles.getEditableArticle(42L)).thenReturn(detail);
        assertSame(detail,controller.create(dto).getData());assertEquals("10",detail.getRevisionId());
    }
    @Test void feedbackAggregationRequiresMetricsPermissionBeforeAnyRpc(){
        var rpc=mock(AgentRpcClient.class);var admin=mock(AdminConsoleService.class);var controller=new AgentFeaturesController(rpc,admin);
        UserContext.setUserId(7L);doThrow(new BusinessException(403,"无权访问")).when(admin).requirePermission(7L,"metrics.read");
        assertThrows(BusinessException.class,()->controller.report(1,20,"business"));verifyNoInteractions(rpc);
    }
}
