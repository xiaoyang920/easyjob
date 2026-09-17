package com.easyjob.vo;

import lombok.Data;
import java.util.List;

/**
 * 分页返回VO
 * 用于统一封装分页数据，避免直接暴露MyBatis-Plus的IPage
 * 
 * @param <T> 数据类型
 */
@Data
public class PageVO<T> {
    
    /**
     * 数据列表
     */
    private List<T> records;
    
    /**
     * 总记录数
     */
    private Long total;
    
    /**
     * 每页显示条数
     */
    private Long size;
    
    /**
     * 当前页
     */
    private Long current;
    
    /**
     * 总页数
     */
    private Long pages;
    
    /**
     * 是否有上一页
     */
    private Boolean hasPrevious;
    
    /**
     * 是否有下一页
     */
    private Boolean hasNext;
    
    /**
     * 无参构造
     */
    public PageVO() {
    }
    
    /**
     * 全参构造
     */
    public PageVO(List<T> records, Long total, Long size, Long current, Long pages) {
        this.records = records;
        this.total = total;
        this.size = size;
        this.current = current;
        this.pages = pages;
        this.hasPrevious = current > 1;
        this.hasNext = current < pages;
    }
    
    /**
     * 从MyBatis-Plus的IPage转换为PageVO
     * 
     * @param page IPage对象
     * @param <T> 数据类型
     * @return PageVO对象
     */
    public static <T> PageVO<T> fromIPage(com.baomidou.mybatisplus.core.metadata.IPage<T> page) {
        PageVO<T> pageVO = new PageVO<>();
        pageVO.setRecords(page.getRecords());
        pageVO.setTotal(page.getTotal());
        pageVO.setSize(page.getSize());
        pageVO.setCurrent(page.getCurrent());
        pageVO.setPages(page.getPages());
        pageVO.setHasPrevious(page.getCurrent() > 1);
        pageVO.setHasNext(page.getCurrent() < page.getPages());
        return pageVO;
    }
    
    /**
     * 从IPage转换，并对数据进行类型转换
     * 
     * @param page IPage对象
     * @param records 转换后的数据列表
     * @param <T> 目标数据类型
     * @return PageVO对象
     */
    public static <T> PageVO<T> fromIPage(com.baomidou.mybatisplus.core.metadata.IPage<?> page, List<T> records) {
        PageVO<T> pageVO = new PageVO<>();
        pageVO.setRecords(records);
        pageVO.setTotal(page.getTotal());
        pageVO.setSize(page.getSize());
        pageVO.setCurrent(page.getCurrent());
        pageVO.setPages(page.getPages());
        pageVO.setHasPrevious(page.getCurrent() > 1);
        pageVO.setHasNext(page.getCurrent() < page.getPages());
        return pageVO;
    }
}
