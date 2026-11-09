# 图片缩略图功能实现文档（WebP 版）

## 1. 依赖配置

在 `pom.xml` 中添加：

```xml
<!-- 缩略图生成 -->
<dependency>
    <groupId>net.coobird</groupId>
    <artifactId>thumbnailator</artifactId>
    <version>0.4.20</version>
</dependency>

<!-- WebP 支持（Maven中央仓库，无需额外仓库配置） -->
<dependency>
    <groupId>org.sejda.imageio</groupId>
    <artifactId>webp-imageio</artifactId>
    <version>0.1.6</version>
</dependency>
```

> `webp-imageio` 基于 Google 的 libwebp 原生库，内置了 Windows/Linux/Mac 的预编译二进制，开箱即用。通过标准 Java ImageIO SPI 注册，引入后 `ImageIO.write(image, "webp", file)` 即可使用。

## 2. 缩略图配置参数

在 `application.yml` 中添加配置：

```yaml
file:
  thumbnail:
    width: 400              # 缩略图宽度（等比缩放）
    quality: 0.75           # 压缩质量 0-1
    categories: covers,articles  # 需要生成缩略图的分类（逗号分隔）
```

## 3. FileController 改造

### 3.1 新增 import

```java
import net.coobird.thumbnailator.Thumbnails;
import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.util.Set;
```

### 3.2 注入缩略图配置参数

```java
@Value("${file.thumbnail.width}")
private int thumbnailWidth;

@Value("${file.thumbnail.quality}")
private float thumbnailQuality;

@Value("#{'${file.thumbnail.categories}'.split(',')}")
private Set<String> thumbnailCategories;
```

### 3.3 新增缩略图生成方法（WebP 输出）

```java
/**
 * 生成 WebP 格式缩略图
 * 
 * @param originalPath 原图路径
 * @param category 文件分类
 * @return 缩略图访问URL，如果不需要生成则返回null
 */
private String generateThumbnail(Path originalPath, String category) {
    // 只有指定分类才生成缩略图
    if (!thumbnailCategories.contains(category)) {
        return null;
    }
    
    try {
        // 缩略图路径：thumbnails/covers/2024/02/22/xxx.webp
        // 使用 Path.relativize() 计算相对路径（比字符串replace更可靠，能正确处理不同操作系统的路径分隔符）
        Path basePath = Paths.get(uploadPath);
        String originalRelative = basePath.relativize(originalPath).toString().replace("\\", "/");
        
        // 替换扩展名为 .webp
        String thumbnailRelative = "thumbnails/" + originalRelative.replaceAll("\\.[^.]+$", ".webp");
        
        Path thumbnailPath = Paths.get(uploadPath, thumbnailRelative);
        
        // 创建目录
        Files.createDirectories(thumbnailPath.getParent());
        
        // 使用 Thumbnailator 缩放图片
        BufferedImage scaledImage = Thumbnails.of(originalPath.toFile())
                .width(thumbnailWidth)
                .asBufferedImage();
        
        // 使用 WebP 格式输出（webp-imageio 通过 SPI 自动注册，直接用 ImageIO 即可）
        ImageIO.write(scaledImage, "webp", thumbnailPath.toFile());
        
        log.info("WebP缩略图生成成功: {}", thumbnailPath);
        
        return accessUrl + "/" + thumbnailRelative;
        
    } catch (IOException e) {
        log.error("缩略图生成失败", e);
        // 缩略图生成失败不影响主流程，返回null
        return null;
    }
}
```

### 3.4 修改 saveFile 方法

```java
/**
 * 保存文件到本地（含缩略图生成）
 * 
 * @param file 文件
 * @param category 文件分类
 * @return 包含原图URL和缩略图URL的Map
 */
private Map<String, String> saveFileWithThumbnail(MultipartFile file, String category) {
    try {
        // 获取原始文件名和扩展名
        String originalFilename = file.getOriginalFilename();
        String extension = originalFilename.substring(originalFilename.lastIndexOf("."));

        // 生成唯一文件名 (UUID)
        String fileName = UUID.randomUUID().toString().replace("-", "") + extension;

        // 按日期分目录存储
        String datePath = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
        String relativePath = category + "/" + datePath + "/" + fileName;
        
        // 完整的文件保存路径
        Path filePath = Paths.get(uploadPath, relativePath);

        // 创建目录
        Files.createDirectories(filePath.getParent());

        // 保存原图
        file.transferTo(filePath.toFile());
        
        String fileUrl = accessUrl + "/" + relativePath.replace("\\", "/");
        log.info("文件保存成功: {}", filePath.toAbsolutePath());
        
        // 生成缩略图
        String thumbUrl = generateThumbnail(filePath, category);
        
        Map<String, String> result = new HashMap<>();
        result.put("url", fileUrl);
        if (thumbUrl != null) {
            result.put("thumbUrl", thumbUrl);
        }
        
        return result;

    } catch (IOException e) {
        log.error("文件保存失败", e);
        throw new BusinessException("文件上传失败，请稍后重试");
    }
}
```

### 3.5 修改 uploadImage 方法

```java
private ResponseVO<?> uploadImage(MultipartFile file, String category) {
    log.info("开始上传{}，文件名: {}, 大小: {} bytes", category, file.getOriginalFilename(), file.getSize());
    
    // 验证文件
    validateImageFile(file);
    
    // 保存文件（含缩略图）
    Map<String, String> urls = saveFileWithThumbnail(file, category);
    
    // 返回结果
    Map<String, String> data = new HashMap<>();
    data.put("url", urls.get("url"));
    data.put("fileName", file.getOriginalFilename());
    if (urls.containsKey("thumbUrl")) {
        data.put("thumbUrl", urls.get("thumbUrl"));
    }
    
    log.info("{}上传成功: {}", category, urls.get("url"));
    return ResponseVO.success("上传成功", data);
}
```

## 4. 存储结构

改造后的目录结构：

```
uploads/
├── covers/                    # 封面原图
│   └── 2024/02/22/
│       └── abc123.jpg
├── articles/                  # 文章图片原图
│   └── 2024/02/22/
│       └── def456.png
├── thumbnails/                # 缩略图目录（WebP 格式）
│   ├── covers/
│   │   └── 2024/02/22/
│   │       └── abc123.webp    # 400px宽，quality 0.75，WebP格式
│   └── articles/
│       └── 2024/02/22/
│           └── def456.webp    # PNG→WebP
├── avatars/                   # 头像（不生成缩略图）
├── messages/                  # 消息图片（不生成缩略图）
└── comments/                  # 评论图片（不生成缩略图）
```

## 5. 接口返回格式变化

上传封面图后返回：

```json
{
  "code": 200,
  "message": "上传成功",
  "data": {
    "url": "/uploads/covers/2024/02/22/abc123.jpg",
    "thumbUrl": "/uploads/thumbnails/covers/2024/02/22/abc123.webp",
    "fileName": "my-cover.jpg"
  }
}
```

上传头像（不生成缩略图）：

```json
{
  "code": 200,
  "message": "上传成功",
  "data": {
    "url": "/uploads/avatars/2024/02/22/xyz789.jpg",
    "fileName": "avatar.jpg"
  }
}
```

## 6. 前端使用

### 6.1 首页/用户空间文章列表

使用 `thumbUrl`（如果有）：

```vue
<img :src="article.coverThumbUrl || article.coverImage" />
```

### 6.2 文章详情页

使用原图 `url`：

```vue
<img :src="article.coverImage" />
```

### 6.3 数据库字段

不需要新增 `cover_thumb_url` 字段。前端已通过 `getThumbUrl()` 工具函数根据原图路径自动拼接缩略图路径（`/uploads/xxx.jpg` → `/uploads/thumbnails/xxx.webp`），并配合 `v-lazyload` 指令的 `fallback` 机制在缩略图不存在时自动回退原图。这样做的好处：

- 无需修改数据库表结构和现有接口
- 缩略图路径与原图路径存在确定的映射关系，无需额外存储
- 前端 `image.ts` 中的 `failedThumbs` 缓存会记住加载失败的缩略图，避免重复请求

## 7. WebP 压缩效果预估

| 原图大小 | WebP缩略图大小 | 压缩比 |
|---------|---------------|-------|
| 3MB     | 15-40KB       | 98%+  |
| 1MB     | 10-30KB       | 97%+  |
| 500KB   | 8-20KB        | 96%+  |

> WebP 比 JPEG 同等画质下体积小 25%-35%

## 8. 注意事项

1. GIF 动图生成缩略图后会变成静态图（只保留第一帧）
2. 缩略图生成失败不影响原图上传，只是返回结果中没有 `thumbUrl`
3. 删除原图时需要同时删除对应的缩略图（注意扩展名变成了 `.webp`）
4. 已有的历史图片需要单独写脚本批量生成缩略图
5. `webp-imageio` 基于 libwebp 原生库（非纯 Java），首次加载需初始化原生库，后续调用性能良好
6. 所有主流浏览器（Chrome、Edge、Firefox、Safari 14+）都支持 WebP，IE 不支持但已淘汰
