package com.easyjob.dto;

import com.easyjob.exception.BusinessException;
import lombok.Data;

import java.io.Serializable;

/**
 * 用户修改信息DTO
 * 用于接收前端修改个人资料的请求数据
 */
@Data
public class UserUpdateDTO implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * 昵称（2-20个字符）
     */
    private String nickName;

    /**
     * 头像URL
     */
    private String avatar;

    /**
     * 性别：0.女 1.男 2.未知
     */
    private Integer sex;

    /**
     * 出生日期（格式：yyyy-MM-dd）
     */
    private String birthday;

    /**
     * 个人简介（最多500字符）
     */
    private String personIntroduction;

    /**
     * 学校（最多100字符）
     */
    private String school;

    /**
     * 空间公告（最多500字符）
     */
    private String noticeInfo;

    /**
     * 主题：1.默认主题 2.暗黑主题 3.梦幻主题
     */
    private Integer theme;

    /**
     * 验证昵称是否有效
     */
    public boolean isNickNameValid() {
        return nickName != null 
            && nickName.trim().length() >= 2 
            && nickName.trim().length() <= 20;
    }

    /**
     * 验证性别是否有效
     */
    public boolean isSexValid() {
        return sex == null || (sex >= 0 && sex <= 2);
    }

    /**
     * 验证主题是否有效
     */
    public boolean isThemeValid() {
        return theme == null || (theme >= 1 && theme <= 3);
    }

    /**
     * 验证个人简介长度
     */
    public boolean isPersonIntroductionValid() {
        return personIntroduction == null || personIntroduction.length() <= 500;
    }

    /**
     * 验证学校长度
     */
    public boolean isSchoolValid() {
        return school == null || school.length() <= 100;
    }

    /**
     * 验证空间公告长度
     */
    public boolean isNoticeInfoValid() {
        return noticeInfo == null || noticeInfo.length() <= 500;
    }

    /**
     * 验证生日格式（简单验证）
     */
    public boolean isBirthdayValid() {
        if (birthday == null || birthday.trim().isEmpty()) {
            return true;
        }
        // 简单的格式验证：yyyy-MM-dd
        return birthday.matches("^\\d{4}-\\d{2}-\\d{2}$");
    }

    /**
     * 验证所有字段，失败直接抛异常
     */
    public void validateAndThrow() {
        if (!isNickNameValid()) {
            throw new BusinessException("昵称长度应在2-20个字符之间");
        }
        if (!isSexValid()) {
            throw new BusinessException("性别参数无效");
        }
        if (!isThemeValid()) {
            throw new BusinessException("主题参数无效");
        }
        if (!isPersonIntroductionValid()) {
            throw new BusinessException("个人简介最多500个字符");
        }
        if (!isSchoolValid()) {
            throw new BusinessException("学校名称最多100个字符");
        }
        if (!isNoticeInfoValid()) {
            throw new BusinessException("空间公告最多500个字符");
        }
        if (!isBirthdayValid()) {
            throw new BusinessException("生日格式不正确，应为yyyy-MM-dd格式");
        }
    }
}
