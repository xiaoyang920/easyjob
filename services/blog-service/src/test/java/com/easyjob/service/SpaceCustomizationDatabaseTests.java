package com.easyjob.service;

import com.easyjob.exception.BusinessException;
import com.easyjob.mapper.ArticleAccessMapper;
import com.easyjob.mapper.GrowthMapper;
import com.easyjob.mapper.MapperTestSupport;
import com.easyjob.mapper.SpaceBannerReviewMapper;
import com.easyjob.mapper.SpaceSkinMapper;
import com.easyjob.vo.DecorationSpec;
import com.easyjob.vo.SpaceArtwork;
import com.easyjob.vo.SpaceBannerSubmission;
import com.easyjob.vo.SpaceBannerView;
import com.easyjob.vo.SpaceCustomization.Appearance;
import com.easyjob.vo.SpaceCustomization.ArtworkDraft;
import com.easyjob.vo.SpaceCustomization.ProductEdit;
import com.easyjob.vo.SpaceCustomization.PublishProduct;
import com.easyjob.vo.SpaceCustomization.Purchase;
import com.easyjob.vo.SpaceCustomization.PurchaseOrder;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.transaction.support.TransactionTemplate;

import javax.imageio.ImageIO;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MAPPER_TEST_JDBC_URL", matches = ".+/easyjob_mapper_test_[a-f0-9]+.*")
class SpaceCustomizationDatabaseTests {
    private static final String ARTIST = "测试作者";
    private static final long BUYER = 732L;
    private static final long ADMIN = 739L;
    private JdbcTemplate jdbc;
    private SpaceCustomizationService service;
    private TransactionTemplate transaction;
    private SpaceBannerReviewMapper reviewMapper;
    private SpaceSkinMapper skinMapper;
    private AdminConsoleService admin;
    private FileStorageService files;
    @TempDir Path uploads;

    @BeforeEach
    void setup() {
        DriverManagerDataSource dataSource = new DriverManagerDataSource(System.getenv("MAPPER_TEST_JDBC_URL"),
                System.getenv("MAPPER_TEST_USER"), System.getenv("MAPPER_TEST_PASSWORD"));
        jdbc = new JdbcTemplate(dataSource);
        removeFixtures();
        jdbc.update("DELETE FROM space_banner_review WHERE user_id = ?", BUYER);
        jdbc.update("DELETE FROM user_info WHERE user_id IN (732, 739)");
        jdbc.update("""
            INSERT INTO user_info(user_id,email,nick_name,password,status,role,join_time,current_coin_count,total_coin_count,
                sex,theme,article_count,follower_count,following_count,data_source)
            VALUES(732,'space-test@example.invalid','space-fixture','offline-no-login',1,1,NOW(),50,50,2,1,0,0,0,'evaluation')
            """);
        jdbc.update("""
            INSERT INTO user_info(user_id,email,nick_name,password,status,role,join_time,current_coin_count,total_coin_count,
                sex,theme,article_count,follower_count,following_count,data_source)
            VALUES(739,'space-admin-test@example.invalid','space-admin-fixture','offline-no-login',1,2,NOW(),0,0,2,1,0,0,0,'evaluation')
            """);
        ArticleAccessService access = new ArticleAccessService(
                MapperTestSupport.mapper(dataSource, ArticleAccessMapper.class), null, null, null);
        admin = new AdminConsoleService(null, access, null, null, null, null);
        skinMapper = MapperTestSupport.mapper(dataSource, SpaceSkinMapper.class);
        reviewMapper = MapperTestSupport.mapper(dataSource, SpaceBannerReviewMapper.class);
        files = new FileStorageService(uploads.toString(), "/uploads", 20000000, 10000, 640, .8f, "");
        service = new SpaceCustomizationService(skinMapper,
                MapperTestSupport.mapper(dataSource, GrowthMapper.class), files);
        transaction = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
    }

    @AfterEach
    void cleanup() {
        removeFixtures();
    }

    private void removeFixtures() {
        jdbc.update("DELETE FROM user_equipped_artwork WHERE user_id = ?", BUYER);
        jdbc.update("DELETE FROM user_space_skin WHERE user_id = ?", BUYER);
        jdbc.update("DELETE FROM coin_ledger WHERE user_id = ?", BUYER);
        jdbc.update("DELETE FROM space_product_artwork WHERE skin_id LIKE 'test-pendant-%'");
        jdbc.update("DELETE FROM space_skin WHERE skin_id LIKE 'test-pendant-%'");
        jdbc.update("DELETE FROM space_artwork WHERE artist = ?", ARTIST);
    }

    private static String artworkId(int index) {
        return "art:" + "%024x".formatted(index);
    }

    private static String productId(int index) {
        return "test-pendant-" + index;
    }

    /** Uploads a transparent pendant, saves it as an artwork and lists it as a standalone product. */
    private String listPendant(int index, int price) throws Exception {
        BufferedImage image = new BufferedImage(512, 512, BufferedImage.TYPE_INT_ARGB);
        Graphics2D brush = image.createGraphics();
        try {
            brush.setColor(new Color(60, 80 + index * 7, 140));
            brush.fillOval(index, 30, 80, 65);
        } finally {
            brush.dispose();
        }
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        ImageIO.write(image, "png", encoded);
        String url = (String) files.uploadDecoration(new MockMultipartFile("file", "art.png", "image/png", encoded.toByteArray()),
                DecorationSpec.SPEC.imageRule(SpaceArtwork.PENDANT, "image"), ADMIN).get("url");
        String title = "测试挂件 " + index;
        assertEquals(artworkId(index), service.createArtwork(ADMIN, pendant(artworkId(index), title, url)));
        PublishProduct product = new PublishProduct(productId(index), title, price, List.of(artworkId(index)));
        assertEquals(productId(index), transaction.execute(status -> service.publishProduct(product)));
        return url;
    }

    private static ArtworkDraft pendant(String id, String title, String url) {
        return new ArtworkDraft(id, SpaceArtwork.PENDANT, title, ARTIST, Map.of("image", url), List.of(), Map.of());
    }

    @Test
    void concurrentPurchaseOnlyChargesOnceAndRetryPreservesRequestIdentity() throws Exception {
        listPendant(1, 20);
        listPendant(2, 40);
        listPendant(3, 5);
        UUID request = UUID.randomUUID();
        try (ExecutorService workers = Executors.newFixedThreadPool(2)) {
            CountDownLatch gate = new CountDownLatch(1);
            Future<Purchase> first = workers.submit(() -> {
                gate.await();
                return transaction.execute(status -> service.purchase(BUYER, productId(1), request, 20));
            });
            Future<Purchase> second = workers.submit(() -> {
                gate.await();
                return transaction.execute(status -> service.purchase(BUYER, productId(1), UUID.randomUUID(), 20));
            });
            gate.countDown();
            assertNotEquals(first.get(10, TimeUnit.SECONDS).alreadyOwned(), second.get(10, TimeUnit.SECONDS).alreadyOwned());
        }
        String recorded = jdbc.queryForObject("SELECT request_id FROM user_space_skin WHERE user_id = ?", String.class, BUYER);
        Purchase retry = transaction.execute(status -> service.purchase(BUYER, productId(1), UUID.fromString(recorded), 20));
        assertTrue(retry.alreadyOwned());
        assertEquals(30, retry.balance());
        assertEquals(409, assertThrows(BusinessException.class, () -> transaction.execute(
                status -> service.purchase(BUYER, productId(3), UUID.fromString(recorded), 5))).getCode());
        assertEquals("硬币余额不足", assertThrows(BusinessException.class, () -> transaction.execute(
                status -> service.purchase(BUYER, productId(2), UUID.randomUUID(), 40))).getMessage());
        assertEquals(409, assertThrows(BusinessException.class, () -> transaction.execute(
                status -> service.purchase(BUYER, productId(3), UUID.randomUUID(), 6))).getCode());
        assertEquals(1, jdbc.queryForObject(
                "SELECT COUNT(*) FROM coin_ledger WHERE user_id=732 AND business_type='SKIN' AND delta=-20", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM user_space_skin WHERE user_id=732", Integer.class));
    }

    @Test
    void purchaseHistoryShowsPaidReceiptsForTheOwnerEvenAfterDelisting() {
        int[] prices = {20, 10, 5};
        for (int index = 1; index <= prices.length; index++) {
            String title = "测试挂件 " + index;
            skinMapper.insertArtwork(artworkId(index), SpaceArtwork.PENDANT, title, ARTIST,
                    "{\"images\":{\"image\":\"/uploads/test.png\"},\"items\":[]}", "{}");
            skinMapper.insertProduct(productId(index), title, prices[index - 1]);
            skinMapper.linkArtwork(productId(index), SpaceArtwork.PENDANT, artworkId(index), true);
        }
        transaction.execute(status -> service.purchase(BUYER, productId(1), UUID.randomUUID(), 20));
        transaction.execute(status -> service.purchase(BUYER, productId(2), UUID.randomUUID(), 10));
        jdbc.update("UPDATE user_space_skin SET acquired_at = '2020-01-01 08:00:00' WHERE user_id = ? AND skin_id = ?",
                BUYER, productId(1));
        skinMapper.addOwnership(BUYER, productId(3), UUID.randomUUID().toString(), UUID.randomUUID().toString(), 0);
        jdbc.update("UPDATE space_skin SET listed = FALSE, coin_price = 99 WHERE skin_id = ?", productId(1));

        List<PurchaseOrder> orders = service.purchaseOrders(BUYER);
        assertEquals(List.of("测试挂件 2", "测试挂件 1"), orders.stream().map(PurchaseOrder::title).toList());
        assertEquals(List.of(10, 20), orders.stream().map(PurchaseOrder::coinCost).toList());
        assertEquals(jdbc.queryForObject("SELECT purchase_id FROM user_space_skin WHERE user_id = ? AND skin_id = ?",
                String.class, BUYER, productId(1)), orders.get(1).orderId());
        assertTrue(orders.get(0).createdAt().isAfter(orders.get(1).createdAt()));
        assertTrue(service.purchaseOrders(ADMIN).isEmpty());
    }

    @Test
    void firstAndTwentiethPendantUseIdenticalPublicationPurchaseAndWearPaths() throws Exception {
        for (int index = 1; index <= 20; index++) {
            String art = artworkId(index);
            String product = productId(index);
            String url = listPendant(index, 1);
            int round = index;
            assertEquals(400, assertThrows(BusinessException.class,
                    () -> service.createArtwork(BUYER, pendant(artworkId(round), "冒用", url))).getCode());
            PublishProduct retry = new PublishProduct(product, "测试挂件 " + index, 1, List.of(art));
            assertEquals(product, transaction.execute(status -> service.publishProduct(retry)));
            assertEquals(403, assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(
                    status -> service.wearArtwork(BUYER, SpaceArtwork.PENDANT, art))).getCode());
            UUID request = UUID.randomUUID();
            assertFalse(transaction.execute(status -> service.purchase(BUYER, product, request, 1)).alreadyOwned());
            assertTrue(transaction.execute(status -> service.purchase(BUYER, product, request, 1)).alreadyOwned());
            transaction.executeWithoutResult(status -> service.wearArtwork(BUYER, SpaceArtwork.PENDANT, art));
            assertEquals(url, service.appearance(BUYER).equippedArtworks().get(SpaceArtwork.PENDANT).assets().images().get("image"));
            transaction.executeWithoutResult(status -> service.updateProduct(product, new ProductEdit("测试挂件 " + round, 1, 50, false, 0)));
            assertTrue(service.catalog(BUYER).ownedArtworks().contains(art));
        }
        assertEquals(30, service.catalog(BUYER).balance());
        assertEquals(1, jdbc.queryForObject("SELECT COUNT(*) FROM user_equipped_artwork WHERE user_id=732", Integer.class));

        String last = artworkId(20);
        transaction.executeWithoutResult(status -> service.editArtwork(last, "更正名称", ARTIST, 0));
        assertEquals("更正名称", service.appearance(BUYER).equippedArtworks().get(SpaceArtwork.PENDANT).name());
        assertThrows(BusinessException.class, () -> service.editArtwork(last, "过时", ARTIST, 0));
        assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(status -> service.withdrawArtwork(last, 1)));

        String draft = artworkId(99);
        String asset = service.appearance(BUYER).equippedArtworks().get(SpaceArtwork.PENDANT).assets().images().get("image");
        service.createArtwork(ADMIN, pendant(draft, "可撤回", asset));
        transaction.executeWithoutResult(status -> service.withdrawArtwork(draft, 0));
        assertFalse(service.adminCatalog().artworks().stream().anyMatch(art -> art.artworkId().equals(draft)));
        assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(
                status -> service.publishProduct(new PublishProduct(productId(99), "撤回的作品", 1, List.of(draft)))));

        transaction.executeWithoutResult(status -> service.wearArtwork(BUYER, SpaceArtwork.PENDANT, null));
        assertTrue(service.appearance(BUYER).equippedArtworks().isEmpty());
    }

    @Test
    void standaloneProductRequiresOneUsableArtwork() throws Exception {
        assertEquals(404, assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(
                status -> service.publishProduct(new PublishProduct(productId(1), "挂件", 1, List.of("wreath"))))).getCode());
        listPendant(1, 1);
        assertEquals(409, assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(
                status -> service.publishProduct(new PublishProduct(productId(2), "重复上架", 1, List.of(artworkId(1)))))).getCode());
        assertNull(skinMapper.product(null, productId(2)));
        assertEquals(409, assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(
                status -> service.publishProduct(new PublishProduct(productId(1), "改名", 1, List.of(artworkId(1)))))).getCode());
    }

    @Test
    void chatBubbleUsesOneCompleteTextureAndRejectsOverlappingSlices() throws Exception {
        String bubble = uploadBubbleImage();
        String slot = SpaceArtwork.CHAT_BUBBLE;
        Map<String, Object> slices = Map.of("sliceTop", 33, "sliceRight", 75, "sliceBottom", 72,
                "sliceLeft", 60, "textColor", "#222222");
        var draft = new ArtworkDraft(artworkId(1), slot, "切片气泡", ARTIST, Map.of("image", bubble), List.of(), slices);
        service.createArtwork(ADMIN, draft);
        var saved = service.artworksById(List.of(draft.id())).get(draft.id());
        assertEquals(Map.of("image", bubble), saved.assets().images());
        assertEquals(slices, saved.settings());
        var overlapping = new ArtworkDraft(artworkId(2), slot, "切片过宽", ARTIST, Map.of("image", bubble), List.of(),
                Map.of("sliceTop", 33, "sliceRight", 75, "sliceBottom", 79, "sliceLeft", 60, "textColor", "#222222"));
        assertThrows(BusinessException.class, () -> service.createArtwork(ADMIN, overlapping));
    }

    private String uploadBubbleImage() throws Exception {
        BufferedImage image = new BufferedImage(272, 112, BufferedImage.TYPE_INT_ARGB);
        Graphics2D brush = image.createGraphics();
        try {
            brush.setColor(new Color(60, 100, 140));
            brush.fillRoundRect(4, 9, 256, 91, 46, 46);
        } finally {
            brush.dispose();
        }
        ByteArrayOutputStream encoded = new ByteArrayOutputStream();
        ImageIO.write(image, "png", encoded);
        return (String) files.uploadDecoration(new MockMultipartFile("file", "bubble.png", "image/png", encoded.toByteArray()),
                DecorationSpec.SPEC.imageRule(SpaceArtwork.CHAT_BUBBLE, "image"), ADMIN).get("url");
    }

    @Test
    void bannerPositionBelongsToTheCurrentFile() {
        assertEquals(Appearance.DEFAULT, service.catalog(BUYER).appearance());
        transaction.execute(status -> service.replaceBanner(BUYER, "/uploads/space-banners/example.webp"));
        assertThrows(BusinessException.class,
                () -> transaction.execute(status -> service.updatePosition(BUYER, "/uploads/old.webp", 25)));
        transaction.execute(status -> service.updatePosition(BUYER, "/uploads/space-banners/example.webp", 25));
        Appearance actual = service.appearance(BUYER);
        assertEquals("/uploads/space-banners/example.webp", actual.spaceBannerUrl());
        assertEquals(25, actual.spaceBannerPosition());
    }

    @Test
    void reviewsKeepImagesPrivateUntilApprovalAndRejectStaleDecisions() throws Exception {
        SpaceBannerReviewService reviews = new SpaceBannerReviewService(reviewMapper, skinMapper, files, admin);
        String previous = "/uploads/space-banners/732/2026/11/18/" + "a".repeat(32) + ".webp";
        transaction.execute(status -> service.replaceBanner(BUYER, previous));
        ByteArrayOutputStream raw = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(32, 16, BufferedImage.TYPE_INT_RGB), "png", raw);
        byte[] image = files.prepareSpaceBanner(new MockMultipartFile("file", "banner.png", "image/png", raw.toByteArray()));
        SpaceBannerSubmission first = transaction.execute(status -> reviews.submit(BUYER, image));
        UUID firstId = UUID.fromString(first.reviewId());
        assertArrayEquals(image, reviews.ownerPreview(BUYER, firstId));
        assertThrows(BusinessException.class, () -> reviews.ownerPreview(733L, firstId));
        assertThrows(BusinessException.class, () -> reviews.reviewerPreview(733L, BUYER, firstId));
        assertEquals(previous, service.appearance(BUYER).spaceBannerUrl());
        assertEquals(1, reviews.queue(ADMIN, 1, 10).size());
        SpaceBannerSubmission second = transaction.execute(status -> reviews.submit(BUYER, image));
        UUID secondId = UUID.fromString(second.reviewId());
        assertThrows(BusinessException.class, () -> transaction.executeWithoutResult(
                status -> reviews.decide(ADMIN, BUYER, firstId, true, null)));
        transaction.executeWithoutResult(status -> reviews.decide(ADMIN, BUYER, secondId, false, "请重新上传"));
        assertEquals("请重新上传", reviews.current(BUYER).reason());
        assertEquals(previous, service.appearance(BUYER).spaceBannerUrl());
        assertThrows(BusinessException.class, () -> reviews.ownerPreview(BUYER, secondId));
        try (java.util.stream.Stream<Path> entries = Files.list(uploads)) {
            assertEquals(0, entries.count());
        }
        SpaceBannerSubmission third = transaction.execute(status -> reviews.submit(BUYER, image));
        UUID thirdId = UUID.fromString(third.reviewId());
        SpaceBannerView view = new SpaceBannerView("21:9", 62, 30);
        transaction.execute(status -> reviews.updateView(BUYER, thirdId, view));
        transaction.executeWithoutResult(status -> reviews.decide(ADMIN, BUYER, thirdId, true, null));
        Appearance published = service.appearance(BUYER);
        assertNotEquals(previous, published.spaceBannerUrl());
        assertEquals(30, published.spaceBannerPosition());
        assertEquals(view, published.bannerView());
        assertTrue(Files.isRegularFile(uploads.resolve(published.spaceBannerUrl().substring("/uploads/".length()))));
        assertEquals("APPROVED", reviews.current(BUYER).state());
        assertTrue(reviews.queue(ADMIN, 1, 10).isEmpty());
    }
}
