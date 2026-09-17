package com.easyjob.service.impl;

import cn.hutool.core.bean.BeanUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.easyjob.dto.UserUpdateDTO;
import com.easyjob.dto.NotificationMessage;
import com.easyjob.entity.User;
import com.easyjob.entity.UserFocus;
import com.easyjob.enums.NotificationTypeEnum;
import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.UserFocusMapper;
import com.easyjob.mapper.UserMapper;
import com.easyjob.service.UserService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.UserFollowVO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {
    @Autowired
    private UserMapper userMapper;
    @Autowired
    private UserFocusMapper userFocusMapper;
    @Autowired
    private NotificationServiceImpl notificationService;
    @Override
    public void updateUserSpaceInfo(UserUpdateDTO userUpdateDTO) {
        User user = BeanUtil.copyProperties(userUpdateDTO, User.class);
        int update =userMapper.update(user, new LambdaQueryWrapper<User>().eq(User::getUserId, UserContext.getUserId()));
        if(update==0){
            throw new BusinessException("修改失败");
        }
    }
    /**
     * 获取用户粉丝列表
     * @param userId
     * @return
     */

    @Transactional
    @Override
    public void follow(Long userId) {
        User user = userMapper.selectById(userId);
        if (user== null){
            throw new BusinessException("用户不存在");
        }
        if(userId.equals(UserContext.getUserId())){
            throw new BusinessException("不能关注自己");
        }
        if(userFocusMapper.exists(new LambdaQueryWrapper<UserFocus>().eq(UserFocus::getFocusUserId,userId)
                .eq(UserFocus::getUserId,UserContext.getUserId()))){
            throw new BusinessException("已关注,不能重复关注");
        }
        UserFocus userFocus = new UserFocus();
        userFocus.setUserId(UserContext.getUserId());
        userFocus.setFocusUserId(userId);
        userFocus.setFocusTime(LocalDateTime.now());
        userFocusMapper.insert(userFocus);
        
        // 更新当前用户的关注数 +1
        userMapper.changeFollowingCount(UserContext.getUserId(), 1);
        // 更新目标用户的粉丝数 +1
        userMapper.changeFollowerCount(userId, 1);

        // 发送关注通知给被关注者
        User follower = userMapper.selectById(UserContext.getUserId());
        notificationService.send(NotificationMessage.builder()
                .userId(userId)
                .senderId(UserContext.getUserId())
                .senderNickname(follower != null ? follower.getNickName() : null)
                .senderAvatar(follower != null ? follower.getAvatar() : null)
                .type(NotificationTypeEnum.FOLLOW.getCode())
                .targetId(UserContext.getUserId())
                .content("关注了你")
                .build()
        );
    }
    @Transactional
    @Override
    public void unfollow(Long userId) {
        int delete = userFocusMapper.delete(new LambdaQueryWrapper<UserFocus>().eq(UserFocus::getFocusUserId,userId)
                .eq(UserFocus::getUserId,UserContext.getUserId()));
        if(delete==0){
            throw new BusinessException("取消关注失败,您未关注该用户");
        }
        
        // 更新当前用户的关注数 -1
        userMapper.changeFollowingCount(UserContext.getUserId(), -1);
        // 更新目标用户的粉丝数 -1
        userMapper.changeFollowerCount(userId, -1);
    }
    
    @Override
    public boolean checkFollowStatus(Long userId) {
        Long currentUserId = UserContext.getUserId();
        if (currentUserId == null) {
            return false;
        }
        return userFocusMapper.exists(new LambdaQueryWrapper<UserFocus>()
                .eq(UserFocus::getFocusUserId, userId)
                .eq(UserFocus::getUserId, currentUserId));
    }

    @Override
    public User getUserByEmail(String email) {
        return userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getEmail, email));
    }
}