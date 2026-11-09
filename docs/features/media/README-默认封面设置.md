# 设置默认文章封面

## 步骤

### 1. 创建图片目录
在项目中创建图片目录：
```
src/main/resources/static/images/
```

### 2. 保存默认封面图片
将你提供的山水画图片保存为：
```
src/main/resources/static/images/default-cover.jpg
```

### 3. 图片要求
- **文件名**：`default-cover.jpg`
- **建议尺寸**：1200x800 或 16:9 比例
- **格式**：JPG 或 PNG
- **文件大小**：建议小于 500KB

## 已修改的文件

### user-space.html（个人空间）
- 添加了 `DEFAULT_COVER` 常量指向 `/images/default-cover.jpg`
- 修改文章卡片图片显示逻辑：
  ```javascript
  <img src="${article.coverImage || article.cover || DEFAULT_COVER}" 
       alt="${article.title}" 
       class="article-cover" 
       onerror="this.src='${DEFAULT_COVER}'">
  ```

## 工作原理

1. **优先级判断**：
   - 首先尝试使用 `article.coverImage`（后端返回的封面）
   - 如果为空，使用 `article.cover`（兼容旧数据）
   - 如果都为空，使用 `DEFAULT_COVER`（默认封面）

2. **错误处理**：
   - 添加了 `onerror` 事件
   - 如果图片加载失败（如链接失效），自动显示默认封面

## 目录结构

```
easyjob/
├── src/
│   └── main/
│       └── resources/
│           └── static/
│               ├── images/              # 新建目录
│               │   └── default-cover.jpg  # 默认封面图片
│               ├── user-space.html      # 已修改
│               ├── draft-box.html
│               └── ...其他HTML文件
```

## 注意事项

1. 确保图片路径正确：`/images/default-cover.jpg`
2. 图片需要放在 `static/images/` 目录下才能被访问
3. 如果使用其他图片名称，需要修改 `DEFAULT_COVER` 常量
4. 重启 Spring Boot 应用后生效

## 测试

1. 保存图片到正确位置
2. 重启应用
3. 访问个人空间页面
4. 查看没有封面的文章，应该显示默认封面
