package com.easyjob.config;

import com.easyjob.interceptor.JwtInterceptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web配置类
 * 注册拦截器
 */
@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    @Autowired
    private JwtInterceptor jwtInterceptor;

    /**
     * 文件上传路径
     */
    @Value("${file.upload.path}")
    private String uploadPath;

    /**
     * 配置静态资源访问
     * 将 /uploads/** 映射到本地文件系统
     */
    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        // 配置上传文件的访问路径
        registry.addResourceHandler("/uploads/**")
                .addResourceLocations("file:" + uploadPath + "/");
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(jwtInterceptor)
                // 拦截所有请求
                .addPathPatterns("/**")
                // 排除登录接口
                .excludePathPatterns("/api/auth/**")
                .excludePathPatterns("/api/user/space/**")
                .excludePathPatterns("/test/**")
                // 排除文章详情（公开看）
                .excludePathPatterns("/api/article/list") // 文章列表
                .excludePathPatterns("/api/article/detail/**")
                .excludePathPatterns("/api/article/recommend") // 推荐文章（未登录返回热门）
                .excludePathPatterns("/api/comment/list")// 评论
                .excludePathPatterns("/api/comment/replies")
                // 排除搜索接口（公开）
                .excludePathPatterns("/api/search/**")
                // 排除静态资源（所有HTML、CSS、JS文件）
                .excludePathPatterns("/**/*.html")
                .excludePathPatterns("/**/*.css")
                .excludePathPatterns("/**/*.js")
                .excludePathPatterns("/**/*.png")
                .excludePathPatterns("/**/*.jpg")
                .excludePathPatterns("/**/*.jpeg")
                .excludePathPatterns("/**/*.gif")
                .excludePathPatterns("/**/*.ico")
                // 排除上传文件访问
                .excludePathPatterns("/uploads/**")
                // 排除根路径
                .excludePathPatterns("/");
    }
}
