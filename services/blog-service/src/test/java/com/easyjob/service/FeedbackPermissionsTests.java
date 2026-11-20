package com.easyjob.service;

import com.easyjob.agent.controller.AgentFeaturesController;
import com.easyjob.agent.rpc.AgentRpcClient;
import com.easyjob.exception.BusinessException;
import com.easyjob.utils.UserContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class FeedbackPermissionsTests {
    final AgentRpcClient rpc=mock(AgentRpcClient.class);
    final AdminConsoleService admin=mock(AdminConsoleService.class);
    final AgentFeaturesController controller=new AgentFeaturesController(rpc,admin);
    final String rid="117f57d9-93d7-42de-8de4-491eb297b823";
    @AfterEach void clean(){UserContext.clear();}
    @Test void statisticsPermissionDoesNotGrantAccessToQuestionAndAnswer(){
        UserContext.setUserId(7L);
        doThrow(new BusinessException(403,"denied")).when(admin).requirePermission(7L,"feedback.read");
        assertThrows(BusinessException.class,()->controller.feedbackDetail(rid));verifyNoInteractions(rpc);
    }
    @Test void reviewRequiresItsOwnPermissionBeforeRpc(){
        UserContext.setUserId(7L);
        doThrow(new BusinessException(403,"denied")).when(admin).requirePermission(7L,"feedback.manage");
        assertThrows(BusinessException.class,()->controller.reviewFeedback(rid,new AgentFeaturesController.FeedbackReview("resolved","done",0L,rid,rid)));verifyNoInteractions(rpc);
    }
    @Test void authorizedDetailUsesAdministratorIdentity(){
        UserContext.setUserId(9L);controller.feedbackDetail(rid);
        verify(admin).requirePermission(9L,"feedback.read");verify(rpc).edit(9L,"feedback_detail",rid,java.util.Map.of());
    }
}
