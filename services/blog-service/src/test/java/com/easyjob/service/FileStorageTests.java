package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.vo.DecorationSpec;
import com.easyjob.vo.DecorationSpec.ImageRule;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;
import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.file.*;
import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.Path;
import java.util.Map;

class FileStorageTests {
    private static final ImageRule PENDANT = DecorationSpec.SPEC.imageRule("avatarPendant", "image");
    @TempDir Path root;
    FileStorageService service(long pixels) { return new FileStorageService(root.toString(), "/uploads", pixels, 10000, 640, .8f, "covers"); }
    Path stored(Map<String, Object> upload) {
        return root.resolve(((String) upload.get("url")).substring("/uploads/".length()));
    }
    MockMultipartFile png(String filename, int width, int height) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB), "png", bytes);
        return new MockMultipartFile("file", filename, "image/png", bytes.toByteArray());
    }
    @Test void ownerCanDeleteButAnotherUserAndLegacyAddressesCannot() throws Exception {
        FileStorageService files = service(20000000);
        Map<String, String> result = files.upload(png("x.png", 20, 30), "articles", 7L);
        assertTrue(result.get("path").startsWith("articles/7/"));
        assertEquals(403, assertThrows(BusinessException.class, () -> files.delete(result.get("url"), 8L)).getCode());
        assertTrue(Files.exists(root.resolve(result.get("path"))));
        assertThrows(BusinessException.class, () -> files.delete("/uploads/articles/2025/01/01/old.png", 7L));
        files.delete(result.get("url"), 7L);
        assertFalse(Files.exists(root.resolve(result.get("path"))));
    }
    @Test void rejectsTraversalForeignUrlsAndEncodedPaths() {
        for (String url : new String[]{"/uploads/../x", "/uploads/articles/7/../../x", "/uploads/articles/7/%2e%2e/x", "https://other/x", "/uploads/articles\\7\\x"})
            assertThrows(BusinessException.class, () -> service(1000).delete(url, 7L), url);
    }
    @Test void rejectsFakeImagesMismatchedExtensionsAndExcessivePixels() throws Exception {
        assertThrows(BusinessException.class, () -> service(1000).upload(new MockMultipartFile("file", "x.jpg", "image/jpeg", "not a picture".getBytes()), "articles", 7L));
        MockMultipartFile mismatched = png("x.jpg", 10, 10);
        assertThrows(BusinessException.class, () -> service(1000).upload(mismatched, "articles", 7L));
        MockMultipartFile tooLarge = png("x.png", 40, 40);
        assertThrows(BusinessException.class, () -> service(1000).upload(tooLarge, "articles", 7L));
    }
    @Test void visionUploadIsJpegAndPreservesAspectRatio() throws Exception {
        Map<String, String> result = service(20000000).upload(png("portrait.png", 600, 3000), "ai-chat", 7L);
        Path file = root.resolve(result.get("path"));
        assertEquals(0xff, Files.readAllBytes(file)[0] & 0xff);
        BufferedImage image = ImageIO.read(file.toFile());
        assertEquals(1920, image.getHeight()); assertEquals(384, image.getWidth());
        assertEquals(0xffffff, image.getRGB(100,100) & 0xffffff);
    }
    @Test void thumbnailAddressOnlyReturnedForAnExistingImage() throws Exception {
        Map<String, String> result = service(20000000).upload(png("cover.png", 100, 60), "covers", 7L);
        if (result.containsKey("thumbUrl")) {
            Path thumb = root.resolve(result.get("thumbUrl").substring("/uploads/".length()));
            assertTrue(Files.size(thumb) > 0); assertNotNull(ImageIO.read(thumb.toFile()));
            service(20000000).delete(result.get("url"), 7L);
            assertFalse(Files.exists(thumb));
        } else assertTrue(Files.exists(root.resolve(result.get("path"))));
    }
    @Test void authenticationIsRequiredForStorageOperations() throws Exception {
        MockMultipartFile file = png("x.png",10,10);
        assertEquals(401, assertThrows(BusinessException.class, () -> service(1000).upload(file,"articles",null)).getCode());
        assertEquals(401, assertThrows(BusinessException.class, () -> service(1000).delete("/uploads/x",null)).getCode());
    }

    @Test void trueColorPngTransparencyKeySurvivesPendantUpload() throws Exception {
        BufferedImage rgb = new BufferedImage(256, 256, BufferedImage.TYPE_INT_RGB);
        rgb.setRGB(8, 9, 0xff103040);
        ByteArrayOutputStream source = new ByteArrayOutputStream();
        assertTrue(ImageIO.write(rgb, "png", source));
        byte[] png = source.toByteArray();
        assertEquals(2, png[25]); // RGB without an explicit alpha channel
        byte[] chunk = {'t', 'R', 'N', 'S', 0, 0x10, 0, 0x30, 0, 0x40};
        java.util.zip.CRC32 crc = new java.util.zip.CRC32();
        crc.update(chunk);
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        java.io.DataOutputStream out = new java.io.DataOutputStream(result);
        out.write(png, 0, 33);
        out.writeInt(6);
        out.write(chunk);
        out.writeInt((int) crc.getValue());
        out.write(png, 33, png.length - 33);
        Map<String, Object> upload = service(20000000).uploadDecoration(new MockMultipartFile(
                "file", "rgb-color-key.png", "image/png", result.toByteArray()), PENDANT, 7L);
        BufferedImage stored = ImageIO.read(stored(upload).toFile());
        assertEquals(0, stored.getRGB(8, 9) >>> 24);
        assertEquals(255, stored.getRGB(0, 0) >>> 24);
    }

    @Test void pendantsRequireRealTransparencyAndStaticSquareArtwork() throws Exception {
        FileStorageService files = service(20000000);
        for (int size : new int[]{128, 1025}) assertThrows(BusinessException.class, () -> files.uploadDecoration(png("s.png", size, size), PENDANT, 7L));
        assertThrows(BusinessException.class, () -> files.uploadDecoration(png("s.png", 512, 256), PENDANT, 7L));
        assertThrows(BusinessException.class, () -> files.uploadDecoration(png("empty.png", 256, 256), PENDANT, 7L));
        BufferedImage pixels = new BufferedImage(512, 512, BufferedImage.TYPE_INT_ARGB);
        java.awt.Graphics2D brush = pixels.createGraphics();
        try { brush.fillRect(0, 0, 512, 512); } finally { brush.dispose(); }
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        ImageIO.write(pixels, "png", bytes);
        assertThrows(BusinessException.class, () -> files.uploadDecoration(new MockMultipartFile("file", "opaque.png", "image/png", bytes.toByteArray()), PENDANT, 7L));
        pixels.setRGB(256, 256, 0);
        for (String format : java.util.List.of("png", "webp")) {
            ByteArrayOutputStream encoded = new ByteArrayOutputStream();
            assertTrue(ImageIO.write(pixels, format, encoded));
            Map<String, Object> uploaded = files.uploadDecoration(new MockMultipartFile("file", "ring." + format,
                    "image/" + format, encoded.toByteArray()), PENDANT, 7L);
            String url = (String) uploaded.get("url");
            assertTrue(url.endsWith(".png"));
            BufferedImage stored = ImageIO.read(stored(uploaded).toFile());
            assertEquals(512, stored.getWidth());
            assertEquals(0, stored.getRGB(256, 256) >>> 24);
            assertEquals(512, files.requireDecorationImage(url, PENDANT, 7L).width());
            assertThrows(BusinessException.class, () -> files.requireDecorationImage(url, PENDANT, 8L));
            assertThrows(BusinessException.class, () -> files.requireDecorationImage("https://example.invalid/ring.png", PENDANT, 7L));
        }
        byte[] apng = bytes.toByteArray();
        System.arraycopy(new byte[]{'a', 'c', 'T', 'L'}, 0, apng, 12, 4);
        assertTrue(assertThrows(BusinessException.class, () -> files.uploadDecoration(
                new MockMultipartFile("file", "animated.png", "image/png", apng), PENDANT, 7L)).getMessage().contains("静态"));
        byte[] webp = "RIFFxxxxWEBPANIMxxxx".getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        assertThrows(BusinessException.class, () -> files.uploadDecoration(
                new MockMultipartFile("file", "animated.webp", "image/webp", webp), PENDANT, 7L));
    }
    @Test void spaceBannerKeepsOriginalFramingAndCanOnlyBeRemovedThroughCustomization() throws Exception {
        FileStorageService files = service(20000000);
        byte[] prepared = files.prepareSpaceBanner(png("photo.png", 640, 800));
        try (java.util.stream.Stream<Path> entries = Files.list(root)) {
            assertEquals(0, entries.count());
        }
        Map<String, String> result = files.publishSpaceBanner(prepared, 7L);
        Path banner = root.resolve(result.get("path"));
        Path thumbnail = root.resolve(result.get("thumbUrl").substring("/uploads/".length()));
        assertTrue(banner.toString().endsWith(".webp"));
        BufferedImage image = ImageIO.read(banner.toFile());
        assertEquals(640, image.getWidth());
        assertEquals(800, image.getHeight());
        assertEquals(640, ImageIO.read(thumbnail.toFile()).getWidth());
        assertThrows(BusinessException.class, () -> files.delete(result.get("url"), 7L));
        files.discardSpaceBanner(result.get("url"), 7L);
        assertFalse(Files.exists(banner));
        assertFalse(Files.exists(thumbnail));
    }
    @Test void commentAttachmentsMustBeExistingCommentUploadsOwnedByTheAuthor() throws Exception {
        FileStorageService files=service(1000);
        Map<String, String> image=files.upload(png("comment.png",10,10),"comments",7L);
        assertDoesNotThrow(()->files.requireCommentImage(image.get("url"),7L));
        assertThrows(BusinessException.class,()->files.requireCommentImage(image.get("url"),8L));
        Map<String, String> articleImage=files.upload(png("article.png",10,10),"articles",7L);
        assertThrows(BusinessException.class,()->files.requireCommentImage(articleImage.get("url"),7L));
        files.delete(image.get("url"),7L);
        assertThrows(BusinessException.class,()->files.requireCommentImage(image.get("url"),7L));
    }
    @Test void commentAttachmentsRejectExternalInlineAndTraversalAddresses() {
        for(String url:new String[]{"https://example.org/x.png","data:image/png;base64,AAAA","/uploads/comments/7/../../x.png","/uploads/comments/7/2026/10/20/%2e.png"})
            assertThrows(BusinessException.class,()->service(1000).requireCommentImage(url,7L));
        assertEquals(401,assertThrows(BusinessException.class,()->service(1000).requireCommentImage("/uploads/x",null)).getCode());
    }
}
