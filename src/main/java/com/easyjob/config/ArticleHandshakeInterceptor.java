package com.easyjob.config;

import cn.hutool.core.bean.BeanUtil;
import com.easyjob.component.RedisComponent;
import com.easyjob.dto.UserInfo;
import com.easyjob.entity.User;
import com.easyjob.mapper.UserMapper;
import com.easyjob.utils.JwtUtil;
import com.easyjob.vo.UserSpaceVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import java.util.Map;

@Component
@Slf4j
public class ArticleHandshakeInterceptor implements HandshakeInterceptor {
    @Autowired
    private JwtUtil jwtUtil;
    @Autowired
    private RedisComponent redisComponent;
    @Autowired
    private UserMapper userMapper;
    /**
     * 握手前，验证token，把userinfo存入attributes
     * @param request
     * @param response
     * @param wsHandler
     * @param attributes
     * @return
     * @throws Exception
     */
    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) throws Exception {
        if(request instanceof ServletServerHttpRequest){
            ServletServerHttpRequest serverHttpRequest = (ServletServerHttpRequest) request;
            String token = serverHttpRequest.getServletRequest().getParameter("token");
            if(token != null){
                try{
                    Long userId = jwtUtil.getUserIdFromToken(token);
                    UserSpaceVO userSpaceVO = redisComponent.getUserSpaceVO(userId);
                    
                    String avatar;
                    String nickName;
                    
                    // 如果Redis没有数据，从数据库获取
                    if (userSpaceVO == null) {
                        log.info("用户缓存已过期，从数据库重新获取，userId: {}", userId);
                        User user = userMapper.selectById(userId);
                        if (user == null) {
                            log.warn("用户不存在，userId: {}", userId);
                            return false;
                        }
                        avatar = user.getAvatar();
                        nickName = user.getNickName();
                        
                        // 重新缓存到Redis（复制完整的用户信息）
                        UserSpaceVO newUserSpaceVO = BeanUtil.copyProperties(user, UserSpaceVO.class);
                        redisComponent.saveUserSpaceVO(userId, newUserSpaceVO);
                    } else {
                        avatar = userSpaceVO.getAvatar();
                        nickName = userSpaceVO.getNickName();
                    }
                    
                    UserInfo userInfo = new UserInfo();
                    userInfo.setUserId(userId.toString());
                    userInfo.setAvatar(avatar);
                    userInfo.setNickName(nickName);
                    attributes.put("userInfo", userInfo);
                    return true;//允许连接
                } catch (Exception e) {
                    log.warn("用户token解析失败（忽略）: {}", e.getMessage());
                }
            }
        }
        return false;//拒绝连接
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response, WebSocketHandler wsHandler, Exception exception) {
        // do nothing
    }
}
