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
    @Autowired private com.easyjob.service.SocialService social;
    @Autowired
    private UserMapper userMapper;
    @Autowired
    private UserFocusMapper userFocusMapper;
    @Autowired
    private NotificationServiceImpl notificationService;
    @Override
    public void updateUserSpaceInfo(UserUpdateDTO userUpdateDTO) {
        UserUpdateDTO dto=userUpdateDTO;
        int update=userMapper.update(null,new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<User>()
            .eq(User::getUserId,UserContext.getUserId()).set(dto.getNickName()!=null,User::getNickName,dto.getNickName())
            .set(dto.getAvatar()!=null,User::getAvatar,dto.getAvatar()).set(dto.getSex()!=null,User::getSex,dto.getSex()).set(dto.getBirthday()!=null,User::getBirthday,dto.getBirthday())
            .set(dto.getPersonIntroduction()!=null,User::getPersonIntroduction,dto.getPersonIntroduction()).set(dto.getSchool()!=null,User::getSchool,dto.getSchool())
            .set(dto.getNoticeInfo()!=null,User::getNoticeInfo,dto.getNoticeInfo()).set(dto.getTheme()!=null,User::getTheme,dto.getTheme()));
        if(update==0){
            throw new BusinessException("修改失败");
        }
    }
    /**
     * 获取用户粉丝列表
     * @param userId
     * @return
     */

    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    @Override
    public void follow(Long userId) {
        social.follow(UserContext.getUserId(),userId,true);
    }
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.READ_COMMITTED)
    @Override
    public void unfollow(Long userId) {
        social.follow(UserContext.getUserId(),userId,false);
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
