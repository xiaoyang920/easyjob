package com.easyjob.vo;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/** Space decoration data: designer-made artworks, the products that sell them, and what a user wears. */
public final class SpaceCustomization {
    private SpaceCustomization() {}
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final TypeReference<Map<String, String>> ARTWORK_MAP = new TypeReference<>() {};

    /** Public look of a personal space: the reviewed banner plus one equipped artwork per slot. */
    public record Appearance(String spaceBannerUrl, int spaceBannerPosition, @JsonIgnore String bannerViewJson,
                             Map<String, SpaceArtwork> equippedArtworks) {
        public static final Appearance DEFAULT = new Appearance(null, 50, null, Map.of());

        public Appearance(String banner, int position, String view) {
            this(banner, position, view, Map.of());
        }

        public Appearance withArtworks(Map<String, SpaceArtwork> artworks) {
            return new Appearance(spaceBannerUrl, spaceBannerPosition, bannerViewJson, artworks);
        }

        public Appearance withoutBanner() {
            return new Appearance(null, 50, null, equippedArtworks);
        }

        @JsonProperty("spaceBannerView")
        public SpaceBannerView bannerView() {
            return SpaceBannerView.read(bannerViewJson, spaceBannerPosition);
        }
    }

    /** A shop product. It grants every linked artwork; a standalone product sells exactly one artwork. */
    public record Product(String productId, String name, int coinPrice, boolean listed, boolean owned,
                          int sortOrder, int version, String standaloneArtworkId, @JsonIgnore String artworksJson) {
        @JsonProperty("artworks")
        public Map<String, String> artworks() {
            if (artworksJson == null) return Map.of();
            try {
                return JSON.readValue(artworksJson, ARTWORK_MAP);
            } catch (JsonProcessingException invalid) {
                throw new IllegalStateException("Invalid product artwork mapping " + productId, invalid);
            }
        }

        public Product withOwned(boolean value) {
            return new Product(productId, name, coinPrice, listed, value, sortOrder, version, standaloneArtworkId, artworksJson);
        }
    }

    /** {@code quotes} holds the price this user pays for each product they do not own yet. */
    public record Catalog(Appearance appearance, List<Product> products, int balance,
                          List<SpaceArtwork> artworks, List<String> ownedArtworks, Map<String, Quote> quotes) {}

    /** A personal price: bundles are reduced by the share of artworks the user already owns. */
    public record Quote(int price, int ownedArtworks, int totalArtworks) {}

    public record AdminCatalog(List<Product> products, List<SpaceArtwork> artworks) {}

    /** One artwork makes a standalone product; several artworks (one per slot) make a bundle. */
    public record PublishProduct(String id, String name, Integer price, List<String> artworkIds) {}

    /**
     * A new artwork as submitted by the admin. {@code images} are keyed by the slot's image fields,
     * {@code items} fill the slot's list (in order), {@code settings} are keyed by the slot's settings.
     */
    public record ArtworkDraft(String id, String slot, String name, String artist, Map<String, String> images,
                               List<DraftItem> items, Map<String, Object> settings) {
        public record DraftItem(String name, String url) {}
    }

    public record ProductEdit(String name, Integer price, Integer sortOrder, Boolean listed, Integer version) {}

    public record Purchase(String productId, int balance, boolean alreadyOwned) {}

    /** Receipt for a completed coin purchase. */
    public record PurchaseOrder(String orderId, String title, int coinCost, Instant createdAt) {}
}
