# AI 聊天图片上传压缩方案

# 当前实现说明

本文的智谱识图流程已经移除。AI 对话使用 DeepSeek 原生图片输入，上传端继续压缩图片；详见 [原生图片输入](../../agent/runtime/native-image-input.md)。

## 问题

生产环境下 ImageUnderstandingService 直接把原图 URL 传给智谱 API，大图（尤其是 PNG）超过智谱限制导致 1210 错误。

## 方案

AI聊天图片不需要保留原图。上传时直接从 MultipartFile 读取，经 Thumbnailator 压缩后一步写入磁盘，不走 `saveFile`，避免多余IO。

## 压缩策略

1. 原图是 JPEG 且 ≤2MB 且 宽高均≤1920px → 直接 `transferTo` 保存，不经过 Thumbnailator
2. 否则：Thumbnailator 从 InputStream 读取 → `size(1920, 1920)` 等比缩放（只缩不放） + 质量0.85 + 输出 JPEG
3. 统一输出 `.jpg` 扩展名

## 改动范围

仅 `FileController.java`，无其他文件改动。

---

## FileController.java 改动

### 1. 新增常量

```java
/** AI图片最大边长 */
private static final int AI_IMAGE_MAX_DIMENSION = 1920;
/** AI图片免压缩阈值（2MB） */
private static final long AI_IMAGE_MAX_BYTES = 2 * 1024 * 1024;
```

### 2. 重写 uploadAiChat 方法

不再调用 `saveFile`，直接处理压缩和保存：

```java
@PostMapping("/upload-ai-chat")
public ResponseVO<?> uploadAiChat(@RequestParam("file") MultipartFile file) {
    Long userId = com.easyjob.utils.UserContext.getUserId();
    if (userId == null) {
        throw new BusinessException("请先登录");
    }
    
    log.info("上传AI聊天图片，用户ID: {}, 文件名: {}, 大小: {}KB", 
            userId, file.getOriginalFilename(), file.getSize() / 1024);
    validateImageFile(file);
    
    try {
        // 构建保存路径（统一 .jpg 扩展名）
        String datePath = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
        String fileName = UUID.randomUUID().toString().replace("-", "") + ".jpg";
        String relativePath = "ai-chat/" + userId + "/" + datePath + "/" + fileName;
        Path outputPath = Paths.get(uploadPath, relativePath);
        Files.createDirectories(outputPath.getParent());
        
        if (needsCompression(file)) {
            // 需要压缩：从 InputStream 直接压缩写入
            BufferedImage originalImage = ImageIO.read(file.getInputStream());
            if (originalImage == null) {
                throw new BusinessException("无法解析图片文件");
            }
            int w = originalImage.getWidth();
            int h = originalImage.getHeight();
            int targetW = Math.min(w, AI_IMAGE_MAX_DIMENSION);
            int targetH = Math.min(h, AI_IMAGE_MAX_DIMENSION);
            
            Thumbnails.of(originalImage)
                    .size(targetW, targetH)
                    .outputQuality(0.85)
                    .outputFormat("jpeg")
                    .toFile(outputPath.toFile());
            
            log.info("AI图片压缩保存: {}x{} → {}KB", w, h, Files.size(outputPath) / 1024);
        } else {
            // 无需压缩：直接保存原文件
            file.transferTo(outputPath.toFile());
            log.info("AI图片直接保存: {}KB", file.getSize() / 1024);
        }
        
        Map<String, String> data = new HashMap<>();
        data.put("url", accessUrl + "/" + relativePath);
        data.put("path", relativePath);
        
        return ResponseVO.success("上传成功", data);
        
    } catch (BusinessException e) {
        throw e;
    } catch (IOException e) {
        log.error("AI聊天图片保存失败", e);
        throw new BusinessException("图片上传失败，请稍后重试");
    }
}

/**
 * 判断是否需要压缩
 * JPEG 且 ≤2MB 且 宽高≤1920px → 不需要
 */
private boolean needsCompression(MultipartFile file) throws IOException {
    String originalFilename = file.getOriginalFilename();
    if (originalFilename == null) return true;
    
    String ext = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();
    
    // 非JPEG格式 → 需要压缩（转JPEG）
    if (!"jpg".equals(ext) && !"jpeg".equals(ext)) {
        return true;
    }
    // 超过2MB → 需要压缩
    if (file.getSize() > AI_IMAGE_MAX_BYTES) {
        return true;
    }
    // 检查尺寸
    BufferedImage img = ImageIO.read(file.getInputStream());
    if (img == null) return true;
    return img.getWidth() > AI_IMAGE_MAX_DIMENSION || img.getHeight() > AI_IMAGE_MAX_DIMENSION;
}
```

### 注意事项

- `needsCompression` 中 `ImageIO.read(file.getInputStream())` 会消费一次 InputStream，但 Spring 的 MultipartFile 支持多次调用 `getInputStream()`，所以后续 `Thumbnails.of(originalImage)` 用的是 BufferedImage 对象，不受影响
- 如果不需要压缩，直接 `transferTo` 保存，但扩展名统一改成了 `.jpg`。对于本身就是 JPEG 的文件没问题；如果未来想保留原扩展名，可以在不压缩分支用原始扩展名
