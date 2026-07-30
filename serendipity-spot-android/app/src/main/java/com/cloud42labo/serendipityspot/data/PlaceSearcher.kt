package com.cloud42labo.serendipityspot.data

import android.content.Context
import android.location.Geocoder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.Locale

/** 検索結果の1件。 */
data class PlaceResult(
    val name: String,
    val subtitle: String,
    val lat: Double,
    val lng: Double,
)

/**
 * 住所・駅名・施設名から座標を引く。
 *
 * Android 標準の [Geocoder] を使う。Google Play 開発者サービスが入っている端末では
 * Google のジオコーディングを叩くため、別途 API キーを発行する必要がない。
 * Places API の方が候補の質は高いが、有効化と課金設定が増えるので試作では使わない。
 */
class PlaceSearcher(private val context: Context) {

    /**
     * [nearLat]/[nearLng] を中心にした矩形内を優先して探す。指定しないと日本全国が
     * 対象になり、同名の地名が離れた県でヒットする（例:「マリンピア」で新潟県がヒット）。
     */
    suspend fun search(
        query: String,
        nearLat: Double? = null,
        nearLng: Double? = null,
    ): List<PlaceResult> = withContext(Dispatchers.IO) {
        if (query.isBlank()) return@withContext emptyList()
        if (!Geocoder.isPresent()) return@withContext emptyList()

        val geocoder = Geocoder(context, Locale.JAPAN)
        // 33+ にコールバック版があるが、こちらも動く。分岐を増やす利点が薄いので統一する。
        @Suppress("DEPRECATION")
        val addresses = runCatching {
            if (nearLat != null && nearLng != null) {
                geocoder.getFromLocationName(
                    query,
                    MAX_RESULTS,
                    nearLat - SEARCH_BOUNDS_DEGREES,
                    nearLng - SEARCH_BOUNDS_DEGREES,
                    nearLat + SEARCH_BOUNDS_DEGREES,
                    nearLng + SEARCH_BOUNDS_DEGREES,
                )
            } else {
                geocoder.getFromLocationName(query, MAX_RESULTS)
            }
        }.getOrNull().orEmpty()

        addresses.mapNotNull { address ->
            val line = address.getAddressLine(0)
            val name = address.featureName ?: line ?: return@mapNotNull null
            PlaceResult(
                name = name,
                subtitle = line.orEmpty(),
                lat = address.latitude,
                lng = address.longitude,
            )
        }
    }

    companion object {
        private const val MAX_RESULTS = 8

        /** 検索の中心から見た矩形の半幅（度）。約55kmを想定。 */
        private const val SEARCH_BOUNDS_DEGREES = 0.5
    }
}
