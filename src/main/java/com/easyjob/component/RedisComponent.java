package com.easyjob.component;


import com.easyjob.constants.RedisConstants;
import com.easyjob.entity.AiMessage;
import com.easyjob.utils.RedisUtils;
import com.easyjob.vo.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;


@Component
public class RedisComponent {
    @Autowired
    private RedisUtils redisUtils;
    /**
     * 保存AI会话上下文
     */
    public void saveConversationContext(Long conversationId, List<AiMessage> messages) {
        redisUtils.setex(RedisConstants.REDIS_KEY_AI_CONV + conversationId, messages, RedisConstants.CODE_EXPIRE_2HOUR);
    }

    /**
     * 获取AI会话上下文
     */
    @SuppressWarnings("unchecked")
    public List<AiMessage> getConversationContext(Long conversationId) {
        return (List<AiMessage>) redisUtils.get(RedisConstants.REDIS_KEY_AI_CONV + conversationId);
    }

    /**
     * 删除AI会话上下文
     */
    public void deleteConversationContext(Long conversationId) {
        redisUtils.delete(RedisConstants.REDIS_KEY_AI_CONV + conversationId);
    }
    /**
     * 保存验证码
     * @param email
     * @param code
     */
    public void saveCheckCode(String email, String code){
        redisUtils.setex(RedisConstants.REDIS_KEY_CHECK_CODE + email, code, RedisConstants.CODE_EXPIRE_5MINUTE);
    }
    /**
     * 获取验证码
     * @param email
     * @return
     */
    public String getCheckCode(String email){
        return (String) redisUtils.get(RedisConstants.REDIS_KEY_CHECK_CODE + email);
    }
    /**
     * 删除验证码
     * @param email
     */
    public void deleteCheckCode(String email){
        redisUtils.delete(RedisConstants.REDIS_KEY_CHECK_CODE + email);
    }
    /**
     * 判断key是否存在
     * @param email
     * @return
     */
    public boolean hasKey(String email) {
        return redisUtils.keyExists(email);
    }
    public void saveTimeKey(String email){
        redisUtils.setex(RedisConstants.REDIS_KEY_CHECK_TIME_CODE+email, "1", RedisConstants.CODE_EXPIRE_1MINUTE);
    }
    /**
     * 刷新用户空间信息的过期时间（用于用户在线时续期）
     * @param userId
     */
    public void refreshUserSpaceExpire(Long userId) {
        redisUtils.expire(RedisConstants.REDIS_KEY_USER_SPACE_INFO + userId, RedisConstants.CODE_EXPIRE_10MINUTE);
    }
    /**
     * 获取用户空间信息
     * @param userId
     * @return
     */
    public UserSpaceVO getUserSpaceVO(Long userId){
        return (UserSpaceVO) redisUtils.get(RedisConstants.REDIS_KEY_USER_SPACE_INFO+userId);
    }
    /**
     * 保存用户空间信息
     * @param userId
     * @param userSpaceVO
     */
    public void saveUserSpaceVO(Long userId, UserSpaceVO userSpaceVO){
        redisUtils.setex(RedisConstants.REDIS_KEY_USER_SPACE_INFO+userId, userSpaceVO, RedisConstants.CODE_EXPIRE_10MINUTE);
    }
    /**
     * 删除用户空间信息
     * @param userId
     */
    public void deleteUserSpaceVO(Long userId){
        redisUtils.delete(RedisConstants.REDIS_KEY_USER_SPACE_INFO+userId);
    }
    /**
     * 保存文章详情
     * @param articleId
     * @param articleDetail
     */
    public void saveArticleDetail(Long articleId, ArticleDetailVO articleDetail){
        redisUtils.setex(RedisConstants.REDIS_KEY_ARTICLE_DETAIL+articleId, articleDetail, RedisConstants.CODE_EXPIRE_1HOUR);
    }
    /**
     * 获取文章详情
     * @param articleId
     * @return
     */
    public ArticleDetailVO getArticleDetail(Long articleId){
        return (ArticleDetailVO) redisUtils.get(RedisConstants.REDIS_KEY_ARTICLE_DETAIL+articleId);
    }
    /**
     * 删除文章详情
     * @param articleId
     */
    public void deleteArticleDetail(Long articleId){
        redisUtils.delete(RedisConstants.REDIS_KEY_ARTICLE_DETAIL+articleId);
    }
    /**
     * 保存文章浏览量key（防止刷去观看量，15秒内只统计一次）
     */
    public void saveViewCount(Long articleId, Long userId) {
        redisUtils.setex(RedisConstants.REDIS_KEY_VIEW+articleId+userId, 1, RedisConstants.CODE_EXPIRE_10MINUTE);
    }
    /**
     * 判断文章浏览量key是否存在
     */
    public boolean hasViewCount(Long articleId, Long userId) {
        return redisUtils.keyExists(RedisConstants.REDIS_KEY_VIEW+articleId+userId);
    }
    /**
     * 保存文章分类
     */
    public void saveCategories(List<CategoryVO>  categories){
        redisUtils.setex(RedisConstants.REDIS_KEY_CATEGORIES, categories, RedisConstants.CODE_EXPIRE_24HOUR);
    }
    /**
     * 获取文章分类
     */
    public List<CategoryVO> getCategories(){
        return (List<CategoryVO>) redisUtils.get(RedisConstants.REDIS_KEY_CATEGORIES);
    }
    /**
     * 保存热门标签
     */
    public void saveHotTags(List<TagVO>  hotTags){
        redisUtils.setex(RedisConstants.REDIS_KEY_HOT_TAGS, hotTags, RedisConstants.CODE_EXPIRE_1HOUR);
    }
    /**
     * 获取热门标签
     */
    public List<TagVO> getHotTags(){
        return (List<TagVO>) redisUtils.get(RedisConstants.REDIS_KEY_HOT_TAGS);
    }
    /**
     * 添加AI文章卡片（追加，ai一次对话可能调用多次tool）
     */
    public void addArticleCards(Long conversationId, List<ArticleCardVO> cards){
        if(cards== null|| cards.isEmpty()){
            return;
        }
        String key = RedisConstants.REDIS_KEY_AI_ARTICLE_CARDS+conversationId;
        List<ArticleCardVO> existing = (List<ArticleCardVO>) redisUtils.get(key);
        if(existing == null){
            existing = new ArrayList<>();
        }
        Set<String> existingIds = existing.stream().map(ArticleCardVO::getArticleId).collect(Collectors.toSet());
        for (ArticleCardVO card : cards) {
            if (!existingIds.contains(card.getArticleId())) {
                existing.add(card);
                existingIds.add(card.getArticleId());
            }
        }
        redisUtils.setex(key, existing, RedisConstants.CODE_EXPIRE_5MINUTE);
    }
    public List<ArticleCardVO> getAndClearArticleCards(Long conversationId){
        String key = RedisConstants.REDIS_KEY_AI_ARTICLE_CARDS+conversationId;
        List<ArticleCardVO> cards = (List<ArticleCardVO>) redisUtils.get(key);
        redisUtils.delete(key);
        if(cards == null){
            return new ArrayList<>();
        }
        return cards;
    }
    public void saveView(Long userId, Long articleId){
        String viewKey = RedisConstants.REDIS_KEY_ARTICLE_VIEW + userId + ":" + articleId;
        redisUtils.setex(viewKey, 1, RedisConstants.CODE_EXPIRE_24HOUR);
    }
}
