package com.easyjob.enums;

public enum SearchOrderTypeEnum {
    ARTICLE_LIKE(0,"likeCount","文章点赞数"),
    ARTICLE_TIME(1,"createTime","文章时间"),
    ARTICLE_COMMENT(2,"commentCount","评论数"),
    ARTICLE_COLLECT(3,"collectCount","文章收藏");
    private Integer type;
    private String field;
    private String desc;
    SearchOrderTypeEnum(Integer type, String field, String desc) {
        this.type = type;
        this.field = field;
        this.desc = desc;
    }
    public static SearchOrderTypeEnum getByType(Integer type) {
        for (SearchOrderTypeEnum value : SearchOrderTypeEnum.values()) {
            if (value.getType().equals(type)) {
                return value;
            }
        }
        return null;
    }

    public Integer getType() {
        return type;
    }

    public String getField() {
        return field;
    }

    public String getDesc() {
        return desc;
    }
}
