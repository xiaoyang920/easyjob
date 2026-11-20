package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.MessageVO;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import com.easyjob.mapper.MapperTestSupport;
import com.easyjob.mapper.SocialMapper;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Supplier;
import static org.junit.jupiter.api.Assertions.*;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;

/** Executed only against the disposable schema created by scripts/test-social.py. */
@EnabledIfEnvironmentVariable(named="SOCIAL_TEST_JDBC_URL",matches=".+/easyjob_social_test_[a-z0-9]+.*")
class SocialDatabaseTests {
    static JdbcTemplate jdbc;static TransactionTemplate tx;static SocialService social;
    @BeforeAll static void database(){
        DriverManagerDataSource ds=new DriverManagerDataSource(System.getenv("SOCIAL_TEST_JDBC_URL"),System.getenv("SOCIAL_TEST_USERNAME"),System.getenv("SOCIAL_TEST_PASSWORD"));
        jdbc=new JdbcTemplate(ds);tx=new TransactionTemplate(new DataSourceTransactionManager(ds));tx.setIsolationLevel(TransactionDefinition.ISOLATION_READ_COMMITTED);
        social=new SocialService(MapperTestSupport.mapper(ds,SocialMapper.class));
    }
    <T>T transaction(Supplier<T> work){return tx.execute(status->work.get());}
    void run(Runnable work){transaction(()->{work.run();return null;});}
    long open(long a,long b){return Long.parseLong(transaction(()->social.open(a,b)).getConversationId());}
    void send(long cid,long uid,long mid,String text){run(()->{social.lockChat(cid,uid);social.admit(cid,uid,1,text);jdbc.update("INSERT INTO message(message_id,conversation_id,sender_id,content,message_type,status) VALUES(?,?,?,?,1,0)",mid,cid,uid,text);jdbc.update("UPDATE conversation SET last_message_id=?,last_message_content=LEFT(?,100),last_message_time=NOW() WHERE conversation_id=?",mid,text,cid);jdbc.update("UPDATE conversation_member SET unread_count=unread_count+1,is_deleted=0 WHERE conversation_id=? AND user_id<>?",cid,uid);});}
    @BeforeEach void fixtures(){
        for(String table:List.of("message","direct_chat_alias","direct_chat_state","conversation_member","conversation","user_contact_setting","user_block","user_focus","user_social_setting","article_info","user_info"))jdbc.update("DELETE FROM "+table);
        for(long uid=7;uid<40;uid++)jdbc.update("INSERT INTO user_info(user_id,nick_name,status) VALUES(?,?,1)",uid,"用户"+uid);
        ReflectionTestUtils.setField(social,"dailyLimit",20);
        ReflectionTestUtils.setField(social,"enabled",true);
    }
    @Test void relationshipsContactsAndRemarksAreDirectional(){
        assertEquals(false,social.relationship(7,8).get("isFriend"));run(()->social.follow(7,8,true));assertEquals(true,social.relationship(8,7).get("isFollowedBy"));
        run(()->social.follow(8,7,true));assertEquals(true,social.relationship(7,8).get("isFriend"));
        run(()->social.remark(7,8,"同学"));assertEquals("同学",social.relationship(7,8).get("remark"));assertEquals("",social.relationship(8,7).get("remark"));
        assertEquals(1L,social.contacts(7,"friends","同学",1,10).get("total"));assertEquals(0L,social.contacts(7,"friends","%",1,10).get("total"));
        run(()->social.follow(7,8,false));assertEquals(0L,social.contacts(7,"friends","",1,10).get("total"));assertEquals("同学",social.relationship(7,8).get("remark"));
    }
    @Test void parallelOpenCreatesOneConversation()throws Exception{
        try(ExecutorService pool=Executors.newFixedThreadPool(8)){CountDownLatch start=new CountDownLatch(1);ArrayList<Future<Long>> futures=new ArrayList<Future<Long>>();for(int i=0;i<12;i++)futures.add(pool.submit(()->{start.await();return open(7,8);}));start.countDown();HashSet<Long> ids=new HashSet<Long>();for(Future<Long> future:futures)ids.add(future.get(20,TimeUnit.SECONDS));assertEquals(1,ids.size());assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM conversation",Integer.class));}
    }
    @Test void parallelFollowsKeepCountsAndUniqueness()throws Exception{
        try(ExecutorService pool=Executors.newFixedThreadPool(6)){ArrayList<Future<?>> jobs=new ArrayList<Future<?>>();for(int i=0;i<12;i++){long target=8+i%3;jobs.add(pool.submit(()->run(()->social.follow(7,target,true))));}for(Future<?> job:jobs)job.get(20,TimeUnit.SECONDS);}
        assertEquals(3,jdbc.queryForObject("SELECT following_count FROM user_info WHERE user_id=7",Integer.class));assertEquals(3,jdbc.queryForObject("SELECT COUNT(*) FROM user_focus WHERE user_id=7",Integer.class));
    }
    @Test void pendingRequestCannotBeResetByRecallHideOrOpen(){long cid=open(7,8);assertTrue(social.conversations(8,true).isEmpty());assertTrue(social.conversations(8,false).isEmpty());send(cid,7,101,"你好");assertEquals(1,social.conversations(8,true).size());assertTrue(social.conversations(8,false).isEmpty());
        jdbc.update("UPDATE message SET status=1 WHERE message_id=101");jdbc.update("UPDATE conversation_member SET is_deleted=1 WHERE conversation_id=? AND user_id=7",cid);assertEquals(cid,open(7,8));assertThrows(BusinessException.class,()->send(cid,7,102,"再来一条"));assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM message",Integer.class));}
    @Test void viewingDoesNotAcceptAndOnlyRecipientCanHandle(){long cid=open(7,8);send(cid,7,101,"你好");run(()->social.handleRequest(cid,8,"view"));assertEquals("PENDING",social.conversation(cid,8).getRequestState());assertEquals(0L,social.summary(8).get("requestUnseen"));assertThrows(BusinessException.class,()->run(()->social.handleRequest(cid,7,"accept")));run(()->social.handleRequest(cid,8,"accept"));assertFalse((Boolean)social.relationship(8,7).get("isFollowing"));send(cid,7,102,"已接受后可继续");}
    @Test void declinedSenderCannotRestartAndRecipientCanReply(){long cid=open(7,8);send(cid,7,101,"你好");run(()->social.handleRequest(cid,8,"decline"));assertTrue(social.conversations(8,false).isEmpty());assertEquals(0,social.summary(8).get("messageUnread"));assertEquals(0,social.summary(8).get("requestPending"));assertEquals(1,social.conversations(7,false).size());assertThrows(BusinessException.class,()->send(cid,7,102,"重复申请"));send(cid,8,103,"我现在回复");assertEquals("ACCEPTED",social.conversation(cid,7).getRequestState());assertEquals(1,social.conversations(8,false).size());}
    @Test void privacyAndDailyQuotaAreEnforcedAtSend(){long cid=open(7,8);run(()->social.settings(8,false));assertThrows(BusinessException.class,()->send(cid,7,101,"你好"));run(()->social.settings(8,true));ReflectionTestUtils.setField(social,"dailyLimit",2);send(cid,7,101,"你好");send(open(7,9),7,102,"你好");long last=open(7,10);assertThrows(BusinessException.class,()->send(last,7,103,"超限"));assertEquals("NONE",social.conversation(last,7).getRequestState());}
    @Test void parallelGreetingsOnlyAdmitOneMessage()throws Exception{long cid=open(7,8);try(ExecutorService pool=Executors.newFixedThreadPool(6)){ArrayList<Future<Boolean>> jobs=new ArrayList<Future<Boolean>>();for(int i=0;i<8;i++){long mid=101+i;jobs.add(pool.submit(()->{try{send(cid,7,mid,"你好");return true;}catch(BusinessException denied){return false;}}));}int accepted=0;for(Future<Boolean> job:jobs)if(job.get(20,TimeUnit.SECONDS))accepted++;assertEquals(1,accepted);}assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM message",Integer.class));}
    @Test void pendingGreetingIsPlainTextAndUnicodeLimited(){long cid=open(7,8);assertThrows(BusinessException.class,()->run(()->social.admit(cid,7,2,"/uploads/image.png")));assertThrows(BusinessException.class,()->send(cid,7,101,"😀".repeat(301)));send(cid,7,102,"😀".repeat(300));}
    @Test void mutualUpgradePreservesHistoryAndUnfollowDoesNotCloseChat(){long cid=open(7,8);send(cid,7,101,"招呼");run(()->social.follow(7,8,true));run(()->social.follow(8,7,true));assertEquals("ACCEPTED",social.conversation(cid,7).getRequestState());run(()->social.follow(7,8,false));send(cid,7,102,"正常聊天");assertEquals(2,jdbc.queryForObject("SELECT COUNT(*) FROM message",Integer.class));}
    @Test void blockRemovesFriendshipButKeepsHistoryAndUnblockDoesNotRestoreIt(){run(()->social.follow(7,8,true));run(()->social.follow(8,7,true));long cid=open(7,8);send(cid,7,101,"已有消息");run(()->social.block(7,8,true));assertFalse(social.conversation(cid,8).getCanMessage());assertTrue(social.presenceAudience(8).isEmpty());assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM user_focus",Integer.class));assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM message",Integer.class));run(()->social.block(7,8,false));assertFalse((Boolean)social.relationship(7,8).get("isFriend"));assertFalse(social.conversation(cid,8).getCanMessage());}
    @Test void muteAndReadCursorDoNotDiscardNewUnread(){run(()->social.follow(7,8,true));run(()->social.follow(8,7,true));long cid=open(7,8);send(cid,7,101,"第一条");send(cid,7,102,"第二条");run(()->social.preferences(cid,8,true,true));assertEquals(0,social.summary(8).get("messageUnread"));assertEquals(2,social.conversation(cid,8).getUnreadCount());run(()->social.read(cid,8,101L));assertEquals(1,social.conversation(cid,8).getUnreadCount());send(cid,7,103,"同时到的新消息");run(()->social.read(cid,8,101L));assertEquals(2,social.conversation(cid,8).getUnreadCount());run(()->social.read(cid,8,103L));assertEquals(0,social.conversation(cid,8).getUnreadCount());assertThrows(BusinessException.class,()->run(()->social.read(cid,9,103L)));}
    @Test void articleCardsAndQuotedRecallsUseCurrentAuthoritativeState(){long cid=open(7,8);jdbc.update("INSERT INTO article_info(article_id,user_id,title,status,deleted,required_level) VALUES(55,7,'公开文章',1,0,0)");jdbc.update("INSERT INTO message(message_id,conversation_id,sender_id,message_type,content,status) VALUES(101,?,7,1,'原文',1)",cid);MessageVO card=new MessageVO();card.setMessageType(3);card.setStatus(0);card.setContent("55");card.setConversationId(Long.toString(cid));card.setReplyToMessageId("101");social.enrichMessages(List.of(card));assertEquals("公开文章",card.getArticle().get("title"));assertEquals("原消息已撤回",card.getReplyToContent());jdbc.update("UPDATE article_info SET status=0 WHERE article_id=55");social.enrichMessages(List.of(card));assertEquals(false,card.getArticle().get("available"));assertNull(card.getArticle().get("title"));}
    @Test void disablingNewRequestsPreservesMutualAndExistingChat(){ReflectionTestUtils.setField(social,"enabled",false);long stranger=open(7,8);assertFalse(social.conversation(stranger,7).getCanMessage());assertThrows(BusinessException.class,()->send(stranger,7,101,"招呼"));run(()->social.follow(7,8,true));run(()->social.follow(8,7,true));send(stranger,7,102,"朋友仍可聊天");run(()->social.follow(7,8,false));send(stranger,7,103,"已有许可仍保留");assertEquals(2,jdbc.queryForObject("SELECT COUNT(*) FROM message",Integer.class));}
    @Test void blockingCannotRefundOrTransferDailyRequestQuota(){
        ReflectionTestUtils.setField(social,"dailyLimit",2);send(open(7,8),7,101,"你好");send(open(7,9),7,102,"你好");
        run(()->social.block(7,8,true));run(()->social.block(7,8,false));run(()->social.block(9,7,true));
        long third=open(7,10);assertThrows(BusinessException.class,()->send(third,7,103,"不能重置限额"));
        assertEquals(2,jdbc.queryForObject("SELECT COUNT(*) FROM direct_chat_state WHERE requested_by=7",Integer.class));
        assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM direct_chat_state WHERE requested_by=8 OR requested_by=9",Integer.class));
    }
    @Test void unavailableRealtimeDoesNotTurnCommittedFollowIntoFailure(){
        java.util.function.BiConsumer<Long,String> unavailable=(uid,data)->{throw new IllegalStateException("test relay unavailable");};
        ReflectionTestUtils.setField(com.easyjob.config.ChatWebSocketHandler.class,"relay",unavailable);
        try{assertDoesNotThrow(()->run(()->social.follow(7,8,true)));assertEquals(true,social.relationship(7,8).get("isFollowing"));}
        finally{ReflectionTestUtils.setField(com.easyjob.config.ChatWebSocketHandler.class,"relay",null);}
    }
    @Test void mysqlBooleanStatusSupportsSummaryAndInactiveAccountChecks(){
        assertInstanceOf(Boolean.class,jdbc.queryForObject("SELECT status FROM user_info WHERE user_id=8",Object.class));
        long cid=open(7,8);send(cid,7,101,"招呼");run(()->social.handleRequest(cid,8,"accept"));
        assertEquals(1,social.summary(8).get("messageUnread"));assertTrue(social.conversation(cid,7).getCanMessage());
        jdbc.update("UPDATE user_info SET status=0 WHERE user_id=8");assertFalse(social.conversation(cid,7).getCanMessage());
    }
}
