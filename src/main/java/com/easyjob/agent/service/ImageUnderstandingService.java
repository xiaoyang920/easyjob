package com.easyjob.agent.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.content.Media;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.stereotype.Service;
import org.springframework.util.MimeType;
import org.springframework.util.MimeTypeUtils;
import org.springframework.util.StringUtils;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.stream.ImageOutputStream;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

@Service
@Slf4j
public class ImageUnderstandingService {

    @Value("${file.upload.path}")
    private String uploadPath;

    @Value("${file.base-url:}")
    private String baseUrl;

    /** 图片最大边长（超过则等比缩放） */
    private static final int MAX_IMAGE_DIMENSION = 1920;
    /** 压缩后最大字节数（2MB） */
    private static final long MAX_IMAGE_BYTES = 2 * 1024 * 1024;
    /** 智谱API调用超时时间（秒） */
    private static final int API_TIMEOUT_SECONDS = 120;

    @Autowired
    @Qualifier("zhipuVisionClient")
    private ChatClient zhipuVisionClient;

    /**
     * 图片理解
     */
    public String understandImage(String imagePath) {
        try {
            MimeType mimeType = getMimeType(imagePath);
            Media imageMedia;

            if (StringUtils.hasText(baseUrl)) {
                // 生产环境：URL方式
                String imageUrl = baseUrl + "/" + imagePath;
                imageMedia = Media.builder()
                        .mimeType(mimeType)
                        .data(URI.create(imageUrl))
                        .build();
                log.info("使用URL方式: {}", imageUrl);
            } else {
                // 本地开发：读文件 → 压缩 → Resource
                byte[] imageBytes = Files.readAllBytes(Paths.get(uploadPath, imagePath));
                log.info("原始图片大小: {} KB", imageBytes.length / 1024);

                // 压缩图片（缩放+降质量）
                imageBytes = compressImage(imageBytes, imagePath);
                log.info("压缩后图片大小: {} KB", imageBytes.length / 1024);

                imageMedia = Media.builder()
                        .mimeType(MimeTypeUtils.IMAGE_JPEG)
                        .data(new ByteArrayResource(imageBytes))
                        .build();
                log.info("使用本地文件方式: {}/{}", uploadPath, imagePath);
            }

            // 带超时的API调用
            log.info("开始调用智谱视觉模型...");
            String description = callWithTimeout(imageMedia);
            log.info("图片理解完成，描述长度: {} 字符", description.length());
            return description;

        } catch (TimeoutException e) {
            log.error("图片理解超时({}秒): {}", API_TIMEOUT_SECONDS, imagePath);
            throw new RuntimeException("图片理解超时，请尝试上传较小的图片", e);
        } catch (Exception e) {
            log.error("图片理解失败: {}", imagePath, e);
            throw new RuntimeException("图片理解失败: " + e.getMessage(), e);
        }
    }

    /**
     * 带超时的智谱API调用
     */
    private String callWithTimeout(Media imageMedia) throws Exception {
        CompletableFuture<String> future = CompletableFuture.supplyAsync(() ->
                zhipuVisionClient.prompt()
                        .user(u -> u.text("请用中文解释图片内容，并给出图片的描述。").media(imageMedia))
                        .call()
                        .content()
        );
        try {
            return future.get(API_TIMEOUT_SECONDS, TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            future.cancel(true);
            throw e;
        }
    }

    /**
     * 压缩图片：等比缩放 + JPEG降质量
     * 目标：控制在 MAX_IMAGE_BYTES 以内
     */
    private byte[] compressImage(byte[] originalBytes, String imagePath) {
        try {
            BufferedImage image = ImageIO.read(new ByteArrayInputStream(originalBytes));
            if (image == null) {
                log.warn("无法解析图片，跳过压缩: {}", imagePath);
                return originalBytes;
            }

            int width = image.getWidth();
            int height = image.getHeight();

            // 1. 等比缩放（如果超过最大边长）
            if (width > MAX_IMAGE_DIMENSION || height > MAX_IMAGE_DIMENSION) {
                double scale = Math.min(
                        (double) MAX_IMAGE_DIMENSION / width,
                        (double) MAX_IMAGE_DIMENSION / height
                );
                int newWidth = (int) (width * scale);
                int newHeight = (int) (height * scale);

                BufferedImage resized = new BufferedImage(newWidth, newHeight, BufferedImage.TYPE_INT_RGB);
                Graphics2D g = resized.createGraphics();
                g.setColor(Color.WHITE);
                g.fillRect(0, 0, newWidth, newHeight);
                g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                g.drawImage(image, 0, 0, newWidth, newHeight, null);
                g.dispose();
                image = resized;
                log.info("图片缩放: {}x{} -> {}x{}", width, height, newWidth, newHeight);
            } else if (image.getType() != BufferedImage.TYPE_INT_RGB) {
                // 未缩放但需要转RGB（去掉透明通道，JPEG不支持透明）
                BufferedImage rgb = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
                Graphics2D g = rgb.createGraphics();
                g.setColor(Color.WHITE);
                g.fillRect(0, 0, width, height);
                g.drawImage(image, 0, 0, null);
                g.dispose();
                image = rgb;
            }

            // 2. JPEG压缩（质量从0.85开始，逐步降低直到满足大小要求）
            float quality = 0.9f;
            byte[] compressed = toJpegBytes(image, quality);

            while (compressed.length > MAX_IMAGE_BYTES && quality > 0.3f) {
                quality -= 0.1f;
                compressed = toJpegBytes(image, quality);
                log.debug("JPEG质量调整为 {}, 大小: {} KB", String.format("%.1f", quality), compressed.length / 1024);
            }

            return compressed;

        } catch (Exception e) {
            log.warn("图片压缩失败，使用原图: {}", e.getMessage());
            return originalBytes;
        }
    }

    /**
     * BufferedImage 转 JPEG 字节数组（指定质量）
     */
    private byte[] toJpegBytes(BufferedImage image, float quality) throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        var writers = ImageIO.getImageWritersByFormatName("jpeg");
        if (!writers.hasNext()) {
            throw new RuntimeException("JPEG ImageWriter not found");
        }
        var writer = writers.next();
        ImageWriteParam param = writer.getDefaultWriteParam();
        param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
        param.setCompressionQuality(quality);

        try (ImageOutputStream ios = ImageIO.createImageOutputStream(baos)) {
            writer.setOutput(ios);
            writer.write(null, new IIOImage(image, null, null), param);
        } finally {
            writer.dispose();
        }
        return baos.toByteArray();
    }

    /**
     * 根据文件扩展名获取 MimeType
     */
    private MimeType getMimeType(String imagePath) {
        String ext = imagePath.substring(imagePath.lastIndexOf(".") + 1).toLowerCase();
        return switch (ext) {
            case "png" -> MimeTypeUtils.IMAGE_PNG;
            case "gif" -> MimeTypeUtils.IMAGE_GIF;
            case "webp" -> MimeType.valueOf("image/webp");
            default -> MimeTypeUtils.IMAGE_JPEG;
        };
    }
}
