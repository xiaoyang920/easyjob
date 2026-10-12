package com.easyjob.service;
import com.easyjob.agent.component.ArticleIndexPublisher;
import com.easyjob.component.RedisComponent;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserMapper;
import org.junit.jupiter.api.Test;
import com.easyjob.mapper.AdminConsoleMapper;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class AdminConsoleTests {
    final AdminConsoleMapper store=mock(AdminConsoleMapper.class);
    final ArticleAccessService access=mock(ArticleAccessService.class);
    final UserMapper users=mock(UserMapper.class);
    final ArticleIndexPublisher index=mock(ArticleIndexPublisher.class);
    final AdminConsoleService service=new AdminConsoleService(store,access,mock(ReadingGrowthService.class),mock(RedisComponent.class),users,index);
    void admin(){when(access.isAdmin(7L)).thenReturn(true);}
    void article(int status,int level){
        var row=List.of(Map.<String,Object>of("user_id",8L,"status",status,"required_level",level));
        when(store.findArticleOwner(42L)).thenReturn(row);
        when(store.lockArticle(42L)).thenReturn(row);
    }
    @Test void ordinaryUsersCannotReadOrWriteAdminData(){
        assertThrows(BusinessException.class,()->service.overview(7L));
        assertThrows(BusinessException.class,()->service.users(7L,"",1,20));
        assertThrows(BusinessException.class,()->service.logs(7L,1,20));
        assertThrows(BusinessException.class,()->service.level(7L,42L,0,1));
        assertThrows(BusinessException.class,()->service.visibility(7L,42L,1,2));
        verifyNoInteractions(store,users,index);
    }
    @Test void keywordsAreLiteralAndBounded(){
        assertEquals("%a!!b!%!_%",AdminConsoleService.searchPattern(" a!b%_ "));
        assertThrows(BusinessException.class,()->AdminConsoleService.searchPattern("x".repeat(81)));
    }
    @Test void paginationAndStatusAreBoundedBeforeQuery(){
        admin();assertThrows(BusinessException.class,()->service.articles(7L,"",99,1,20));
        assertThrows(BusinessException.class,()->service.users(7L,"",0,20));
        assertThrows(BusinessException.class,()->service.logs(7L,1,101));
        verifyNoInteractions(store);
    }
    @Test void staleEditsNeverOverwriteNewerLevel(){
        admin();article(1,2);assertThrows(BusinessException.class,()->service.level(7L,42L,1,3));
        verify(access,never()).setRequiredLevel(any(),any(),any());verifyNoInteractions(users,index);
    }
    @Test void draftsCannotBePublishedByModerationEndpoint(){
        admin();article(0,0);assertThrows(BusinessException.class,()->service.visibility(7L,42L,0,1));
        verifyNoInteractions(users,index);
    }
    @Test void repeatedStatusDoesNotIncrementCounts(){
        admin();article(1,0);service.visibility(7L,42L,1,1);verifyNoInteractions(users,index);
    }
}
