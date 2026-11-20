package com.easyjob.controller;

import cn.hutool.core.bean.BeanUtil;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.UserUpdateDTO;
import com.easyjob.entity.User;
import com.easyjob.entity.UserFocus;
import com.easyjob.exception.BusinessException;
import com.easyjob.service.UserFocusService;
import com.easyjob.service.UserService;
import com.easyjob.service.SpaceCustomizationService;
import com.easyjob.utils.JwtUtil;
import com.easyjob.utils.UserContext;
import com.easyjob.vo.ResponseVO;
import com.easyjob.vo.SpaceArtwork;
import com.easyjob.vo.UserSpaceVO;
import com.easyjob.vo.SpaceCustomization.Appearance;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

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
    @Autowired private com.easyjob.service.SocialService social;
    @Autowired
    UserFocusService userFoucsService;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired private com.easyjob.service.ReadingGrowthService readingGrowth;
    @Autowired private JwtUtil jwtUtil;
    @Autowired private SpaceCustomizationService customization;

    @GetMapping("/space/pendants")
    public ResponseVO<Map<String, String>> publicPendants(@RequestParam String ids) {
        if (ids.length() > 1000 || !ids.matches("[1-9][0-9]{0,18}(,[1-9][0-9]{0,18}){0,49}")) {
            throw new BusinessException(400, "头像挂件查询参数无效");
        }
        List<Long> users;
        try {
            users = Arrays.stream(ids.split(",")).map(Long::valueOf).distinct().toList();
        } catch (NumberFormatException error) {
            throw new BusinessException(400, "用户编号无效");
        }
        Map<String, String> urls = new HashMap<>();
        customization.wornArtworks(users, SpaceArtwork.PENDANT).forEach((userId, artwork) -> {
            String image = artwork.assets().images().get("image");
            if (image != null) urls.put(userId.toString(), image);
        });
        return ResponseVO.success(urls);
    }

    /**
     * 获取用户信息
     * 个人空间对所有人公开（拦截器已排除），邮箱和最近登录 IP 只返回给本人。
     * @param userId
     * @return
     */
    @GetMapping("/space/{userId}")
    public ResponseVO<?> getUserInfo(@PathVariable Long userId, HttpServletRequest request) {
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
        Appearance appearance = customization.appearance(userId);
        userSpaceVO.setEquippedArtworks(appearance.equippedArtworks());
        userSpaceVO.setSpaceBannerUrl(appearance.spaceBannerUrl());
        userSpaceVO.setSpaceBannerPosition(appearance.spaceBannerPosition());
        userSpaceVO.setSpaceBannerView(appearance.bannerView());
        if (!userId.equals(jwtUtil.resolveOptionalUserId(request.getHeader("Authorization")))) {
            userSpaceVO.setEmail(null);
            userSpaceVO.setLastLoginIp(null);
        }
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
        return ResponseVO.success(social.relationship(UserContext.getUserId(),userId));
    }

}
