package com.easyjob.mapper;

import org.apache.ibatis.annotations.Mapper;

import java.util.List;
import java.util.Map;

/** Fixed statements with bound parameters; locking reads bypass MyBatis caches. */
@Mapper
public interface SocialMapper {
    int ensurePair(Map<String, ?> params);
    Map<String, Object> lockPair(Map<String, ?> params);
    long countActiveUser(Map<String, ?> params);
    long countBlocks(Map<String, ?> params);
    long countFollows(Map<String, ?> params);
    int acceptPair(Map<String, ?> params);
    List<Map<String, Object>> presenceAudience(Map<String, ?> params);
    Map<String, Object> findPerson(Map<String, ?> params);
    List<Map<String, Object>> findPeople(Map<String, ?> params);
    int insertFollow(Map<String, ?> params);
    int deleteFollow(Map<String, ?> params);
    Map<String, Object> notificationPerson(Map<String, ?> params);
    int recountFollowers(Map<String, ?> params);
    List<Map<String, Object>> lockUsers(Map<String, ?> params);
    int saveRemark(Map<String, ?> params);
    int insertBlock(Map<String, ?> params);
    int deletePairFollows(Map<String, ?> params);
    int declinePair(Map<String, ?> params);
    int deleteBlock(Map<String, ?> params);
    long countRequestsDisabled(Map<String, ?> params);
    int saveSettings(Map<String, ?> params);
    int createConversation(Map<String, ?> params);
    int addMember(Map<String, ?> params);
    int attachConversation(Map<String, ?> params);
    int restoreMember(Map<String, ?> params);
    List<Map<String, Object>> canonicalAliases(Map<String, ?> params);
    Map<String, Object> otherMember(Map<String, ?> params);
    long countMembership(Map<String, ?> params);
    int ensureSettings(Map<String, ?> params);
    Map<String, Object> lockSettings(Map<String, ?> params);
    long countRecentRequests(Map<String, ?> params);
    int requestPair(Map<String, ?> params);
    Map<String, Object> conversation(Map<String, ?> params);
    int markViewed(Map<String, ?> params);
    int restoreConversation(Map<String, ?> params);
    int declineRequest(Map<String, ?> params);
    int pinConversation(Map<String, ?> params);
    int muteConversation(Map<String, ?> params);
    Map<String, Object> lockConversation(Map<String, ?> params);
    long countMessage(Map<String, ?> params);
    int advanceReadCursor(Map<String, ?> params);
    int recountUnread(Map<String, ?> params);
    Map<String, Object> unreadState(Map<String, ?> params);
    List<Map<String, Object>> publicArticle(Map<String, ?> params);
    List<Map<String, Object>> publicArticles(Map<String, ?> params);
    List<Map<String, Object>> quotedMessages(Map<String, ?> params);
    List<Map<String, Object>> contacts(Map<String, ?> params);
    long countContacts(Map<String, ?> params);
    List<Map<String, Object>> conversations(Map<String, ?> params);
}
