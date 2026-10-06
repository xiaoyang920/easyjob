package com.easyjob.controller;

import cn.hutool.core.bean.BeanUtil;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.UserUpdateDTO;
import com.easyjob.entity.User;
import com.easyjob.entity.UserFocus;
import com.easyjob.exception.BusinessException;
import com.easyjob.service.UserFocusService;
import com.easyjob.service.UserService;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import com.easyjob.vo.UserSpaceVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;


/**
 * 用户相关接口
 * 需要登录才能访问
 */
@RestController
@RequestMapping("/api/user")
@Slf4j
public class UserController {

    @Autowired
    UserService userService;
    @Autowired
    UserFocusService userFoucsService;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired private com.easyjob.service.ReadingGrowthService readingGrowth;

    /**
     * 获取用户信息
     * @param userId
     * @return
     */
    @GetMapping("/space/{userId}")
    public ResponseVO<?> getUserInfo(@PathVariable Long userId) {
        UserSpaceVO userSpaceVO=null;
        try {
             userSpaceVO = redisComponent.getUserSpaceVO(userId);
        } catch (Exception e) {
            throw new BusinessException(500, "redis出现错误");
        }
        if (userSpaceVO == null){
            userSpaceVO = BeanUtil.copyProperties(userService.getById(userId),UserSpaceVO.class);
            redisComponent.saveUserSpaceVO(userId, userSpaceVO);
        }
        userSpaceVO.setReadingProgress(readingGrowth.summary(userId));
        return ResponseVO.success(userSpaceVO);
    }
    /**
     * 修改用户信息
     */
    @PutMapping("/update")
    public ResponseVO<?> updateUserInfo(@RequestBody UserUpdateDTO userUpdateDTO) {
        userUpdateDTO.validateAndThrow();
        userService.updateUserSpaceInfo(userUpdateDTO);
        redisComponent.deleteUserSpaceVO(UserContext.getUserId());
        return ResponseVO.success("修改成功");
    }
    /**
     * 获取用户粉丝列表
     */
    @GetMapping("/{userId}/followers")
    public ResponseVO<?> getUserFollowers(@PathVariable Long userId,Integer page,Integer size) {
        return ResponseVO.success(userFoucsService.getUserFollowers(userId, page, size));
    }
    /**
     * 获取用户关注列表
     */
    @GetMapping("/{userId}/following")
    public ResponseVO<?> getUserFollowing(@PathVariable Long userId,Integer page,Integer size) {
        return ResponseVO.success(userFoucsService.getUserFollowing(userId, page, size));
    }
    /**
     * 关注
     */
    @PostMapping("/{userId}/follow")
    public ResponseVO<?> follow(@PathVariable Long userId) {
        userService.follow(userId);
        return ResponseVO.success("关注成功");
    }
    /**
     * 取消关注
     */
    @PostMapping("/{userId}/unfollow")
    public ResponseVO<?> unfollow(@PathVariable Long userId) {
        userService.unfollow(userId);
        return ResponseVO.success("取消关注成功");
    }
    
    /**
     * 检查关注状态
     */
    @GetMapping("/{userId}/follow-status")
    public ResponseVO<?> getFollowStatus(@PathVariable Long userId) {
        boolean isFollowing = userService.checkFollowStatus(userId);
        return ResponseVO.success(new java.util.HashMap<String, Object>() {{
            put("isFollowing", isFollowing);
        }});
    }

}
