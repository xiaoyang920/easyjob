package com.easyjob.service;

import com.easyjob.exception.BusinessException;
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
    @TempDir Path root;
    FileStorageService service(long pixels) { return new FileStorageService(root.toString(), "/uploads", pixels, 10000, 640, .8f, "covers"); }
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
